import pytest
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.backups.models import BackupSchedule, BackupScheduleLog, ScheduleAction
from app.servers.models import Server
from app.users.models import User, Role


class TestBackupScheduleService:
    """BackupSchedule CRUD operation tests"""

    @pytest.fixture
    def test_user(self, db: Session):
        """Test user"""
        user = User(
            username="scheduleuser",
            email="schedule@example.com",
            hashed_password="hashed_password",
            role=Role.operator,
            is_active=True,
            is_approved=True
        )
        db.add(user)
        db.flush()
        return user

    @pytest.fixture
    def test_server(self, db: Session, test_user: User):
        """Test server"""
        server = Server(
            name="schedule-test-server",
            description="Schedule test server",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25575,
            max_memory=1024,
            max_players=20,
            owner_id=test_user.id,
            directory_path="/servers/schedule-test-server"
        )
        db.add(server)
        db.flush()
        return server

    def test_create_schedule_success(self, db: Session, test_server: Server):
        """Schedule creation normal case test"""
        # Create schedule
        schedule = BackupSchedule(
            server_id=test_server.id,
            interval_hours=6,
            max_backups=15,
            enabled=True,
            only_when_running=False
        )
        db.add(schedule)
        db.commit()

        # Verify
        created_schedule = db.query(BackupSchedule).filter(
            BackupSchedule.server_id == test_server.id
        ).first()
        
        assert created_schedule is not None
        assert created_schedule.server_id == test_server.id
        assert created_schedule.interval_hours == 6
        assert created_schedule.max_backups == 15
        assert created_schedule.enabled is True
        assert created_schedule.only_when_running is False

    def test_get_schedule_by_server_id(self, db: Session, test_server: Server):
        """Get schedule by server ID test"""
        # Create schedule
        schedule = BackupSchedule(
            server_id=test_server.id,
            interval_hours=12,
            max_backups=10
        )
        db.add(schedule)
        db.commit()

        # Get test
        found_schedule = db.query(BackupSchedule).filter(
            BackupSchedule.server_id == test_server.id
        ).first()
        
        assert found_schedule is not None
        assert found_schedule.id == schedule.id
        assert found_schedule.server_id == test_server.id

    def test_update_schedule_success(self, db: Session, test_server: Server):
        """Schedule update test"""
        # Create schedule
        schedule = BackupSchedule(
            server_id=test_server.id,
            interval_hours=12,
            max_backups=10,
            enabled=True
        )
        db.add(schedule)
        db.commit()

        original_updated_at = schedule.updated_at

        # Execute update
        schedule.interval_hours = 24
        schedule.max_backups = 5
        schedule.enabled = False
        schedule.only_when_running = False
        db.commit()

        # Verify
        updated_schedule = db.query(BackupSchedule).filter(
            BackupSchedule.id == schedule.id
        ).first()
        
        assert updated_schedule.interval_hours == 24
        assert updated_schedule.max_backups == 5
        assert updated_schedule.enabled is False
        assert updated_schedule.only_when_running is False
        assert updated_schedule.updated_at > original_updated_at

    def test_delete_schedule_success(self, db: Session, test_server: Server):
        """Schedule deletion test"""
        # Create schedule
        schedule = BackupSchedule(
            server_id=test_server.id,
            interval_hours=8,
            max_backups=12
        )
        db.add(schedule)
        db.commit()
        schedule_id = schedule.id

        # Execute deletion
        db.delete(schedule)
        db.commit()

        # Verify
        deleted_schedule = db.query(BackupSchedule).filter(
            BackupSchedule.id == schedule_id
        ).first()
        assert deleted_schedule is None

    def test_list_all_schedules(self, db: Session, test_user: User):
        """Get all schedules list test"""
        # Create multiple servers and schedules
        servers = []
        schedules = []
        
        for i in range(3):
            server = Server(
                name=f"schedule-server-{i}",
                description=f"Schedule server {i}",
                minecraft_version="1.20.1",
                server_type="vanilla",
                port=25580 + i,
                max_memory=1024,
                max_players=20,
                owner_id=test_user.id,
                directory_path=f"/servers/schedule-server-{i}"
            )
            servers.append(server)
            db.add(server)
        
        db.flush()
        
        for i, server in enumerate(servers):
            schedule = BackupSchedule(
                server_id=server.id,
                interval_hours=6 * (i + 1),  # 6, 12, 18
                max_backups=10 + i,          # 10, 11, 12
                enabled=i % 2 == 0           # True, False, True
            )
            schedules.append(schedule)
            db.add(schedule)
        
        db.commit()

        # Get all schedules
        all_schedules = db.query(BackupSchedule).all()
        assert len(all_schedules) == 3

        # Get only enabled schedules
        enabled_schedules = db.query(BackupSchedule).filter(
            BackupSchedule.enabled == True
        ).all()
        assert len(enabled_schedules) == 2

    def test_list_schedules_with_server_relationship(self, db: Session, test_user: User):
        """Get schedule with server information test"""
        # Create server and schedule
        server = Server(
            name="relationship-test-server",
            description="Relationship test",
            minecraft_version="1.20.1",
            server_type="paper",
            port=25590,
            max_memory=2048,
            max_players=50,
            owner_id=test_user.id,
            directory_path="/servers/relationship-test-server"
        )
        db.add(server)
        db.flush()

        schedule = BackupSchedule(
            server_id=server.id,
            interval_hours=4,
            max_backups=20
        )
        db.add(schedule)
        db.commit()

        # Get with relationships
        schedule_with_server = db.query(BackupSchedule).filter(
            BackupSchedule.server_id == server.id
        ).first()
        
        assert schedule_with_server.server.name == "relationship-test-server"
        assert schedule_with_server.server.server_type.value == "paper"
        assert schedule_with_server.server.max_memory == 2048

    def test_schedule_execution_time_management(self, db: Session, test_server: Server):
        """Schedule execution time management test"""
        # Create schedule
        schedule = BackupSchedule(
            server_id=test_server.id,
            interval_hours=6,
            max_backups=10
        )
        db.add(schedule)
        db.commit()

        # Set execution time
        now = datetime.utcnow()
        next_backup = now + timedelta(hours=6)
        
        schedule.last_backup_at = now
        schedule.next_backup_at = next_backup
        db.commit()

        # Verify
        updated_schedule = db.query(BackupSchedule).filter(
            BackupSchedule.id == schedule.id
        ).first()
        
        assert updated_schedule.last_backup_at is not None
        assert updated_schedule.next_backup_at is not None
        assert updated_schedule.next_backup_at > updated_schedule.last_backup_at

    def test_schedule_due_for_backup_query(self, db: Session, test_user: User):
        """Backup execution scheduled search test"""
        # Current time
        now = datetime.utcnow()
        
        # Create 3 servers and schedules
        servers_data = [
            {
                "name": "past-due-server",
                "next_backup": now - timedelta(hours=1),  # Past execution time
                "enabled": True
            },
            {
                "name": "future-backup-server", 
                "next_backup": now + timedelta(hours=1),  # Not yet scheduled
                "enabled": True
            },
            {
                "name": "disabled-server",
                "next_backup": now - timedelta(hours=1),  # Past execution time but disabled
                "enabled": False
            }
        ]
        
        for i, data in enumerate(servers_data):
            server = Server(
                name=data["name"],
                description=f"Test server {i}",
                minecraft_version="1.20.1",
                server_type="vanilla",
                port=25600 + i,
                max_memory=1024,
                max_players=20,
                owner_id=test_user.id,
                directory_path=f"/servers/{data['name']}"
            )
            db.add(server)
            db.flush()
            
            schedule = BackupSchedule(
                server_id=server.id,
                interval_hours=6,
                max_backups=10,
                enabled=data["enabled"],
                next_backup_at=data["next_backup"]
            )
            db.add(schedule)
        
        db.commit()

        # Search for scheduled executions (enabled and past execution time)
        due_schedules = db.query(BackupSchedule).filter(
            BackupSchedule.enabled == True,
            BackupSchedule.next_backup_at <= now
        ).all()
        
        assert len(due_schedules) == 1
        assert due_schedules[0].server.name == "past-due-server"


class TestBackupScheduleLogService:
    """BackupScheduleLog CRUD operation tests"""

    @pytest.fixture
    def test_user(self, db: Session):
        """Test user"""
        user = User(
            username="loguser",
            email="log@example.com",
            hashed_password="hashed_password",
            role=Role.admin,
            is_active=True,
            is_approved=True
        )
        db.add(user)
        db.flush()
        return user

    @pytest.fixture
    def test_server(self, db: Session, test_user: User):
        """Test server"""
        server = Server(
            name="log-test-server",
            description="Log test server",
            minecraft_version="1.20.1",
            server_type="vanilla",
            port=25610,
            max_memory=1024,
            max_players=20,
            owner_id=test_user.id,
            directory_path="/servers/log-test-server"
        )
        db.add(server)
        db.flush()
        return server

    def test_create_schedule_log_success(self, db: Session, test_server: Server, test_user: User):
        """Schedule log creation test"""
        log = BackupScheduleLog(
            server_id=test_server.id,
            action=ScheduleAction.created,
            reason="Schedule created for testing",
            new_config={"interval_hours": 12, "max_backups": 10, "enabled": True},
            executed_by_user_id=test_user.id
        )
        db.add(log)
        db.commit()

        # Verify
        created_log = db.query(BackupScheduleLog).filter(
            BackupScheduleLog.server_id == test_server.id
        ).first()
        
        assert created_log is not None
        assert created_log.action == ScheduleAction.created
        assert created_log.reason == "Schedule created for testing"
        assert created_log.new_config["interval_hours"] == 12
        assert created_log.executed_by_user_id == test_user.id

    def test_get_logs_by_server_id(self, db: Session, test_server: Server, test_user: User):
        """Get logs by server ID test"""
        # Create multiple logs
        actions = [ScheduleAction.created, ScheduleAction.updated, ScheduleAction.executed]
        
        for action in actions:
            log = BackupScheduleLog(
                server_id=test_server.id,
                action=action,
                reason=f"Test {action.value}",
                executed_by_user_id=test_user.id
            )
            db.add(log)
        
        db.commit()

        # Get server logs
        server_logs = db.query(BackupScheduleLog).filter(
            BackupScheduleLog.server_id == test_server.id
        ).order_by(BackupScheduleLog.created_at).all()
        
        assert len(server_logs) == 3
        assert [log.action for log in server_logs] == actions

    def test_get_logs_by_action_type(self, db: Session, test_server: Server, test_user: User):
        """Get logs by action type test"""
        # Create logs with different actions
        log1 = BackupScheduleLog(
            server_id=test_server.id,
            action=ScheduleAction.executed,
            reason="Automated backup execution"
        )
        
        log2 = BackupScheduleLog(
            server_id=test_server.id,
            action=ScheduleAction.skipped,
            reason="Server not running"
        )
        
        log3 = BackupScheduleLog(
            server_id=test_server.id,
            action=ScheduleAction.executed,
            reason="Another automated execution"
        )
        
        db.add_all([log1, log2, log3])
        db.commit()

        # Get only executed actions
        executed_logs = db.query(BackupScheduleLog).filter(
            BackupScheduleLog.server_id == test_server.id,
            BackupScheduleLog.action == ScheduleAction.executed
        ).all()
        
        assert len(executed_logs) == 2
        
        # Get only skipped actions
        skipped_logs = db.query(BackupScheduleLog).filter(
            BackupScheduleLog.server_id == test_server.id,
            BackupScheduleLog.action == ScheduleAction.skipped
        ).all()
        
        assert len(skipped_logs) == 1

    def test_log_with_config_changes(self, db: Session, test_server: Server, test_user: User):
        """Configuration change log test"""
        old_config = {"interval_hours": 12, "max_backups": 10, "enabled": True}
        new_config = {"interval_hours": 6, "max_backups": 15, "enabled": True}
        
        log = BackupScheduleLog(
            server_id=test_server.id,
            action=ScheduleAction.updated,
            reason="Schedule configuration updated",
            old_config=old_config,
            new_config=new_config,
            executed_by_user_id=test_user.id
        )
        db.add(log)
        db.commit()

        # Verify
        created_log = db.query(BackupScheduleLog).filter(
            BackupScheduleLog.action == ScheduleAction.updated
        ).first()
        
        assert created_log.old_config["interval_hours"] == 12
        assert created_log.new_config["interval_hours"] == 6
        assert created_log.old_config["max_backups"] == 10
        assert created_log.new_config["max_backups"] == 15

    def test_system_executed_log(self, db: Session, test_server: Server):
        """System execution log test (no user specified)"""
        log = BackupScheduleLog(
            server_id=test_server.id,
            action=ScheduleAction.executed,
            reason="Automated system execution",
            executed_by_user_id=None  # System execution
        )
        db.add(log)
        db.commit()

        # Verify
        system_log = db.query(BackupScheduleLog).filter(
            BackupScheduleLog.executed_by_user_id.is_(None)
        ).first()
        
        assert system_log is not None
        assert system_log.action == ScheduleAction.executed
        assert system_log.executed_by_user_id is None
        assert system_log.executed_by is None

    def test_log_chronological_order(self, db: Session, test_server: Server, test_user: User):
        """Log chronological order test"""
        import time
        
        # Wait a bit to create time difference
        log1 = BackupScheduleLog(
            server_id=test_server.id,
            action=ScheduleAction.created,
            reason="First action",
            executed_by_user_id=test_user.id
        )
        db.add(log1)
        db.commit()
        
        time.sleep(0.01)  # Ensure time separation
        
        log2 = BackupScheduleLog(
            server_id=test_server.id,
            action=ScheduleAction.updated,
            reason="Second action",
            executed_by_user_id=test_user.id
        )
        db.add(log2)
        db.commit()
        
        time.sleep(0.01)
        
        log3 = BackupScheduleLog(
            server_id=test_server.id,
            action=ScheduleAction.executed,
            reason="Third action"
        )
        db.add(log3)
        db.commit()

        # Get in chronological order
        chronological_logs = db.query(BackupScheduleLog).filter(
            BackupScheduleLog.server_id == test_server.id
        ).order_by(BackupScheduleLog.created_at).all()
        
        assert len(chronological_logs) == 3
        assert chronological_logs[0].action == ScheduleAction.created
        assert chronological_logs[1].action == ScheduleAction.updated
        assert chronological_logs[2].action == ScheduleAction.executed
        assert chronological_logs[0].created_at < chronological_logs[1].created_at
        assert chronological_logs[1].created_at < chronological_logs[2].created_at