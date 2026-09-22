from binner_mcp.config import load_config
from binner_mcp.api.client import BinnerAPIProxy
from collections import defaultdict
import sys


def main():
    # Load configuration with automatic path resolution and environment variable overrides.
    config = load_config()

    # Initialize proxy client.
    client = BinnerAPIProxy(
        base_url=config.base_url,
        username=config.username,
        password=config.password,
        timeout=15.0,
    )

    # Health checks.
    is_alive = client.ping()
    if not is_alive:
        print("Couldn't ping Binner instance!", file=sys.stderr)
        return
    # print(f"Binner reachable: {is_alive}")
    # version_info = client.get_system_version()
    # print(f"Binner Version: {version_info['version']}")

    tokens = client.login()
    # print(f"Logged in. JWT Token: {tokens.jwt_token[:15]}...")
    # user = client.get_identity()
    # print(f"User: {user.name} ({user.email_address}), Admin: {user.is_admin}")

    all_parts = client.list_parts(
        results=-1,
        order_by="BinNumber2",
        direction="Ascending",
    )

    # Build part tree:
    part_tree = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    # print(f"Total parts found: {all_parts.total_items}")
    for part in all_parts.items:
        part_tree[part.location][part.bin_number][part.bin_number2].append(part)
    del part
    
    # Sort by location.
    part_tree = dict(sorted(part_tree.items()))
    # Sort by bin (already sorted by secondary bin on retrieval call, albeit not in natural order).
    for loc in part_tree.keys():
        part_tree[loc] = dict(sorted(part_tree[loc].items()))

    for loc_key, loc_val in part_tree.items():
        print(f"- {loc_key}:")
        for bin1_key, bin1_val in loc_val.items():
            print(f"\t- {bin1_key}:")
            loose_parts = bin1_val.get(None, [])
            loose_parts.extend(bin1_val.get("", []))
            for i, p in enumerate(loose_parts):
                print(f"\t\t{i}. {p.quantity}x {p.part_number}")
            for bin2_key, bin2_val in bin1_val.items():
                if bin2_key is not None and bin2_key != "":
                    print(f"\t\t- {bin2_key}:")
                    for i, p in enumerate(bin2_val):
                        print(f"\t\t\t{i}. {p.quantity}x {p.part_number}")


    return part_tree


if __name__ == "__main__":
    r = main()
    # Expose result to top level to allow interactive console usage.
