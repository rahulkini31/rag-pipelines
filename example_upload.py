"""Upload one local document through the complete ingestion pipeline."""

import argparse

from hybrid_rag import ProductionDocumentSystem


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file_path")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--doc-id")
    args = parser.parse_args()

    system = ProductionDocumentSystem()
    result = system.upload_document(args.file_path, args.tenant_id, args.doc_id)
    print(result)


if __name__ == "__main__":
    main()