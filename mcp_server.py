from stuco_portal.mcp import create_mcp_app
from stuco_portal.extensions import db
from stuco_portal.services.db_utils import ensure_schema_updates
from stuco_portal.services.seed import seed_data


def main():
    app = create_mcp_app()
    with app.app_context():
        db.create_all()
        ensure_schema_updates()
        seed_data()

    print("\n--- MCP SERVER READY ---")
    print(f"MCP: http://{app.config['MCP_HOST']}:{app.config['MCP_PORT']}/mcp/health")
    if app.config.get("MCP_REQUIRE_AUTH", True):
        print("Auth: MCP_API_KEY required via Authorization Bearer or X-MCP-API-KEY")
    print("------------------------")

    app.run(
        host=app.config.get("MCP_HOST", "127.0.0.1"),
        port=app.config.get("MCP_PORT", 5002),
        debug=False,
    )


if __name__ == "__main__":
    main()
