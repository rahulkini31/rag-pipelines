"""Create the DocumentShares table used for cross-tenant sharing."""

from api.sharing import create_shares_table


if __name__ == "__main__":
    table = create_shares_table()
    print(f"Shares table ready: {table.name}")
