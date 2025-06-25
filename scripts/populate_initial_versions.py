#!/usr/bin/env python3
"""
Initial Version Data Migration Script

Populates the database with current version data from external APIs.
This script should be run once after the database models are created
to establish the initial version dataset.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Imports after path manipulation (to suppress linting errors)
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.versions.management import VersionManagementService  # noqa: E402
from app.versions.models import MinecraftVersion  # noqa: E402


async def main():
    """Main migration function"""
    logger.info("Starting initial version data migration...")

    try:
        # Ensure database tables exist
        logger.info("Creating database tables if they don't exist...")
        Base.metadata.create_all(bind=engine)

        # Create database session
        db_session = SessionLocal()

        try:
            # Check if we already have version data
            existing_count = db_session.query(MinecraftVersion).count()
            if existing_count > 0:
                logger.info(f"Database already contains {existing_count} versions.")
                user_input = input(
                    "Do you want to proceed anyway? This will update existing data. (y/N): "
                )
                if user_input.lower() not in ["y", "yes"]:
                    logger.info("Migration cancelled by user.")
                    return

            # Create version management service
            logger.info("Initializing version management service...")
            management_service = VersionManagementService(db_session)

            # Perform initial update from external APIs
            logger.info("Fetching version data from external APIs...")
            result = await management_service.trigger_manual_update(
                server_types=None,  # Update all server types
                force_refresh=True,  # Force refresh to get all data
                user_id=None,  # System operation
            )

            # Report results
            if result.success:
                logger.info("✅ Initial version migration completed successfully!")
                logger.info("📊 Migration summary:")
                logger.info(f"   • Versions added: {result.versions_added}")
                logger.info(f"   • Versions updated: {result.versions_updated}")
                logger.info(f"   • Versions removed: {result.versions_removed}")
                logger.info(f"   • Execution time: {result.execution_time_ms}ms")

                if result.errors:
                    logger.warning(
                        f"⚠️  Migration completed with {len(result.errors)} warnings:"
                    )
                    for error in result.errors:
                        logger.warning(f"   • {error}")

                # Display final counts by server type
                logger.info("\n📈 Final version counts by server type:")
                for server_type in ["vanilla", "paper", "fabric", "forge"]:
                    count = (
                        db_session.query(MinecraftVersion)
                        .filter(MinecraftVersion.server_type == server_type)
                        .count()
                    )
                    logger.info(f"   • {server_type.title()}: {count} versions")

                total_versions = db_session.query(MinecraftVersion).count()
                logger.info(f"   • Total: {total_versions} versions")

            else:
                logger.error("❌ Initial version migration failed!")
                logger.error(f"Error: {result.message}")
                if result.errors:
                    logger.error("Detailed errors:")
                    for error in result.errors:
                        logger.error(f"   • {error}")
                sys.exit(1)

        finally:
            try:
                db_session.close()
            except Exception as e:
                logger.warning(f"Error closing database session: {e}")

    except KeyboardInterrupt:
        logger.info("Migration interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Migration failed with unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Run the migration
    asyncio.run(main())
