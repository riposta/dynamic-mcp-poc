"""Quick manual test script for the MCP Gateway"""
import json


def test_search_servers():
    """Test the search_servers functionality"""
    from gateway.server import search_servers, AVAILABLE_SERVERS

    print("Testing search_servers...")
    print("=" * 60)

    # Test 1: Search all servers
    result = search_servers()
    print(f"\n1. Search all servers:")
    print(json.dumps(result, indent=2))

    # Test 2: Search for specific server
    result = search_servers("weather")
    print(f"\n2. Search for 'weather':")
    print(json.dumps(result, indent=2))

    # Test 3: Search by description
    result = search_servers("database")
    print(f"\n3. Search for 'database':")
    print(json.dumps(result, indent=2))


def test_enable_server():
    """Test the enable_server functionality"""
    from gateway.server import enable_server, enabled_servers

    print("\n\nTesting enable_server...")
    print("=" * 60)

    # Test 1: Enable valid server
    result = enable_server("weather")
    print(f"\n1. Enable weather server:")
    print(json.dumps(result, indent=2))

    # Test 2: Try to enable already enabled server
    result = enable_server("weather")
    print(f"\n2. Enable weather server again:")
    print(json.dumps(result, indent=2))

    # Test 3: Enable another server
    result = enable_server("calculator")
    print(f"\n3. Enable calculator server:")
    print(json.dumps(result, indent=2))

    # Test 4: Try to enable non-existent server
    result = enable_server("nonexistent")
    print(f"\n4. Enable non-existent server:")
    print(json.dumps(result, indent=2))

    # Show enabled servers
    print(f"\n\nCurrently enabled servers: {list(enabled_servers.keys())}")


if __name__ == "__main__":
    test_search_servers()
    test_enable_server()
    print("\n" + "=" * 60)
    print("Tests completed!")
    print("=" * 60)
