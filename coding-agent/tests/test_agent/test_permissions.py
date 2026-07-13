"""Tests for agent.permissions module."""

from coding_agent.agent.permissions import (
    Permission,
    PermissionManager,
    TrustLevel,
    permission_from_str,
)


class TestPermissionEnum:
    def test_values(self):
        assert Permission.READ.value == "read"
        assert Permission.WRITE.value == "write"
        assert Permission.EXECUTE.value == "execute"
        assert Permission.DANGEROUS.value == "dangerous"


class TestPermissionFromStr:
    def test_valid_strings(self):
        assert permission_from_str("read") == Permission.READ
        assert permission_from_str("write") == Permission.WRITE
        assert permission_from_str("execute") == Permission.EXECUTE
        assert permission_from_str("dangerous") == Permission.DANGEROUS

    def test_invalid_defaults_to_read(self):
        assert permission_from_str("bogus") == Permission.READ
        assert permission_from_str("") == Permission.READ


class TestPermissionManager:
    def test_read_always_allowed(self):
        pm = PermissionManager(level=Permission.WRITE)
        assert pm.check("read_file", "read") is True

    def test_write_not_initially_allowed(self):
        pm = PermissionManager(level=Permission.WRITE)
        assert pm.check("write_file", "write") is False

    def test_write_allowed_after_approval(self):
        pm = PermissionManager(level=Permission.WRITE)
        pm.approve_tool("write_file")
        assert pm.check("write_file", "write") is True

    def test_write_approval_is_per_tool(self):
        pm = PermissionManager(level=Permission.WRITE)
        pm.approve_tool("write_file")
        assert pm.check("write_file", "write") is True
        assert pm.check("edit_file", "write") is False

    def test_execute_always_asks(self):
        pm = PermissionManager(level=Permission.EXECUTE)
        assert pm.check("execute_command", "execute") is False

    def test_dangerous_always_asks(self):
        pm = PermissionManager(level=Permission.DANGEROUS)
        assert pm.check("rm", "dangerous") is False

    def test_reset_clears_approvals(self):
        pm = PermissionManager(level=Permission.WRITE)
        pm.approve_tool("write_file")
        assert pm.check("write_file", "write") is True
        pm.reset()
        assert pm.check("write_file", "write") is False

    def test_read_only_level(self):
        pm = PermissionManager(level=Permission.READ)
        assert pm.check("read_file", "read") is True
        assert pm.check("write_file", "write") is False

    def test_invalid_permission_defaults_to_read(self):
        pm = PermissionManager(level=Permission.WRITE)
        assert pm.check("tool", "nonexistent") is True


class TestTrustLevel:
    def test_from_trust_level_readonly(self):
        pm = PermissionManager.from_trust_level(TrustLevel.READONLY)
        assert pm.check("read_file", "read") is True
        assert pm.check("write_file", "write") is False

    def test_from_trust_level_standard(self):
        pm = PermissionManager.from_trust_level(TrustLevel.STANDARD)
        assert pm.check("read_file", "read") is True
        # Write needs approval
        assert pm.check("write_file", "write") is False
        pm.approve_tool("write_file")
        assert pm.check("write_file", "write") is True

    def test_from_trust_level_full(self):
        pm = PermissionManager.from_trust_level(TrustLevel.FULL)
        assert pm.check("read_file", "read") is True
        assert pm.check("write_file", "write") is False
        assert pm.check("execute_command", "execute") is False
