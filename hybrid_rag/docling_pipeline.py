import uuid
from typing import List, Tuple

from transformers import AutoTokenizer
from docling.chunking import HybridChunker
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
)
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.transforms.serializer.markdown import (
    MarkdownParams,
    MarkdownTableSerializer,
)
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.labels import DocItemLabel
from langchain_core.documents import Document


class ProductionSerializerProvider(ChunkingSerializerProvider):
    """Serializes tables as clean Markdown and suppresses empty image tags."""

    def get_serializer(self, doc: DoclingDocument) -> ChunkingDocSerializer:
        return ChunkingDocSerializer(
            doc=doc,
            table_serializer=MarkdownTableSerializer(),
            params=MarkdownParams(image_placeholder=""),
        )


def create_converter() -> DocumentConverter:
    pdf_options = PdfPipelineOptions(do_ocr=True, do_table_structure=True)
    pdf_options.table_structure_options.mode = TableFormerMode.ACCURATE
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options)}
    )


class QwenDoclingChunkingEngine:
    def __init__(
        self,
        tokenizer_model_id: str = "Qwen/Qwen3-Embedding-8B",
        max_tokens: int = 768,
        merge_peers: bool = True,
    ):
        hf_tokenizer = AutoTokenizer.from_pretrained(tokenizer_model_id)
        self.tokenizer = HuggingFaceTokenizer(
            tokenizer=hf_tokenizer,
            max_tokens=max_tokens,
        )
        self.chunker = HybridChunker(
            tokenizer=self.tokenizer,
            merge_peers=merge_peers,
            serializer_provider=ProductionSerializerProvider(),
        )

    def chunk_doclang_document(
        self,
        dl_doc: DoclingDocument,
        tenant_id: str,
        doc_id: str,
        version: int,
        filename: str,
        s3_uri: str,
    ) -> Tuple[List[Document], List[str]]:
        lc_docs: List[Document] = []
        chunk_ids: List[str] = []

        chunks = list(self.chunker.chunk(dl_doc=dl_doc))
        total_chunks = len(chunks)

        for idx, chunk in enumerate(chunks):
            contextualized_text = self.chunker.contextualize(chunk=chunk)
            pages = set()
            item_refs = []
            table_refs = []
            content_labels = set()

            for item in chunk.meta.doc_items:
                item_refs.append(item.self_ref)
                content_labels.add(str(getattr(item, "label", "")))

                if getattr(item, "label", None) == DocItemLabel.TABLE:
                    table_refs.append(item.self_ref)

                for prov in getattr(item, "prov", []):
                    if prov.page_no is not None:
                        pages.add(prov.page_no)

            token_count = self.tokenizer.count_tokens(contextualized_text)
            chunk_uuid = str(
                uuid.uuid5(uuid.NAMESPACE_DNS, f"{tenant_id}_{doc_id}_v{version}_{idx}")
            )
            headings = chunk.meta.headings or []
            metadata = {
                "tenant_id": tenant_id,
                "doc_id": doc_id,
                "doc_version": version,
                "filename": filename,
                "s3_doclang_uri": s3_uri,
                "chunk_index": idx,
                "total_chunks": total_chunks,
                "token_count": token_count,
                "headings": headings,
                "section_path": " / ".join(headings) if headings else "Root",
                "page_numbers": sorted(pages),
                "has_table": len(table_refs) > 0,
                "table_refs": table_refs,
                "doc_item_refs": item_refs,
                "content_types": sorted(content_labels),
                "raw_text": chunk.text,
            }

            lc_docs.append(Document(page_content=contextualized_text, metadata=metadata))
            chunk_ids.append(chunk_uuid)

        return lc_docs, chunk_ids