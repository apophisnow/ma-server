"""RBAC Manager for Music Assistant."""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING, Any

from music_assistant_models.auth import (
    PermissionScope,
    Role,
    User,
    UserRole,
)
from music_assistant_models.errors import (
    AuthenticationRequired,
    InvalidDataError,
)

from music_assistant.constants import MASS_LOGGER_NAME
from music_assistant.controllers.webserver.helpers.auth_middleware import get_current_user
from music_assistant.helpers.api import api_command
from music_assistant.helpers.datetime import utc
from music_assistant.helpers.json import json_dumps, json_loads

# Try to import DEFAULT_ROLES from models, fall back to local definition
try:
    from music_assistant_models.auth import DEFAULT_ROLES  # type: ignore[attr-defined]
except ImportError:
    # Define DEFAULT_ROLES locally if not available in models package
    DEFAULT_ROLES: dict[str, Role] = {
        "admin": Role(
            role_id="admin",
            name="Administrator",
            description="Full system access with all permissions",
            is_system=True,
            permissions=[PermissionScope.SYSTEM_ADMIN],
            created_at=None,
        ),
        "user": Role(
            role_id="user",
            name="Standard User",
            description="Standard user with basic playback and library access",
            is_system=True,
            permissions=[
                PermissionScope.PLAYER_CONTROL,
                PermissionScope.PLAYER_VOLUME,
                PermissionScope.PLAYER_QUEUE,
                PermissionScope.PLAYER_VIEW,
                PermissionScope.LIBRARY_READ,
                PermissionScope.PLAYLIST_READ,
                PermissionScope.PLAYLIST_WRITE,
                PermissionScope.PROVIDER_VIEW,
            ],
            created_at=None,
        ),
        "guest": Role(
            role_id="guest",
            name="Guest",
            description="Limited read-only access",
            is_system=True,
            permissions=[
                PermissionScope.PLAYER_VIEW,
                PermissionScope.LIBRARY_READ,
                PermissionScope.PLAYLIST_READ,
            ],
            created_at=None,
        ),
    }

if TYPE_CHECKING:
    from music_assistant.controllers.webserver.auth import AuthenticationManager

LOGGER = logging.getLogger(f"{MASS_LOGGER_NAME}.rbac")


class RBACManager:
    """Manager for Role-Based Access Control."""

    def __init__(self, auth_manager: AuthenticationManager) -> None:
        """
        Initialize RBAC manager.

        :param auth_manager: AuthenticationManager instance.
        """
        self.auth_manager = auth_manager
        self.mass = auth_manager.mass
        self.database = auth_manager.database
        self.logger = LOGGER
        self._roles_cache: dict[str, Role] = {}

    async def setup(self) -> None:
        """Initialize RBAC system."""
        await self._setup_database()
        await self._initialize_default_roles()
        await self._load_roles_cache()
        self.logger.info("RBAC manager initialized")

    async def _setup_database(self) -> None:
        """Set up RBAC database tables."""
        # Roles table
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS rbac_roles (
                role_id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                is_system INTEGER NOT NULL DEFAULT 0,
                permissions TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        # User-Role assignments (many-to-many)
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS rbac_user_roles (
                user_id TEXT NOT NULL,
                role_id TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                PRIMARY KEY (user_id, role_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (role_id) REFERENCES rbac_roles(role_id) ON DELETE CASCADE
            )
            """
        )

        # Indexes
        await self.database.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_roles_user ON rbac_user_roles(user_id)"
        )
        await self.database.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_roles_role ON rbac_user_roles(role_id)"
        )

        await self.database.commit()

    async def _initialize_default_roles(self) -> None:
        """Initialize default system roles."""
        for role_id, role in DEFAULT_ROLES.items():
            existing = await self.database.get_row("rbac_roles", {"role_id": role_id})
            if not existing:
                await self._store_role(role)
                self.logger.info(f"Created default role: {role.name}")

    async def _load_roles_cache(self) -> None:
        """Load all roles into cache."""
        rows = await self.database.get_rows("rbac_roles", limit=1000)
        self._roles_cache = {}
        for row in rows:
            role = self._role_from_row(row)
            self._roles_cache[role.role_id] = role

    def _role_from_row(self, row: dict[str, Any] | Any) -> Role:
        """Convert database row to Role object."""
        from music_assistant.helpers.api import parse_utc_timestamp

        permissions_data = json_loads(row["permissions"])
        created_at = row["created_at"]
        # Parse string timestamp to datetime if needed
        if isinstance(created_at, str):
            created_at = parse_utc_timestamp(created_at) if created_at else None

        return Role(
            role_id=row["role_id"],
            name=row["name"],
            description=row["description"],
            is_system=bool(row["is_system"]),
            permissions=[PermissionScope(p) for p in permissions_data],
            created_at=created_at,
        )

    async def _store_role(self, role: Role) -> None:
        """Store role in database."""
        if not role.created_at:
            role.created_at = utc()

        # Convert permissions to strings, handling both enums and strings
        permission_strs = []
        for p in role.permissions:
            if isinstance(p, str):
                permission_strs.append(p)
            elif isinstance(p, PermissionScope):
                permission_strs.append(p.value)
            else:
                # Handle any other type by converting to PermissionScope first
                permission_strs.append(PermissionScope(p).value)

        data = {
            "role_id": role.role_id,
            "name": role.name,
            "description": role.description,
            "is_system": 1 if role.is_system else 0,
            "permissions": json_dumps(permission_strs),
            "created_at": role.created_at.isoformat(),
        }

        await self.database.insert_or_replace("rbac_roles", data)
        self._roles_cache[role.role_id] = role

    @api_command("rbac/roles")
    async def list_roles(self) -> list[dict[str, Any]]:
        """
        Get all available roles.

        :return: List of roles.
        """
        return [role.to_dict() for role in self._roles_cache.values()]

    @api_command("rbac/role", required_role="admin")
    async def get_role(self, role_id: str) -> Role | None:
        """
        Get role by ID (admin only).

        :param role_id: The role ID.
        :return: Role object or None.
        """
        return self._roles_cache.get(role_id)

    @api_command("rbac/role/create", required_role="admin")
    async def create_role(
        self,
        name: str,
        description: str,
        permissions: list[str],
    ) -> Role:
        """
        Create a custom role (admin only).

        :param name: Role name.
        :param description: Role description.
        :param permissions: List of permission scope values.
        :return: Created role.
        """
        # Validate permissions
        perm_scopes = []
        for perm in permissions:
            try:
                perm_scopes.append(PermissionScope(perm))
            except ValueError as err:
                raise InvalidDataError(f"Invalid permission: {perm}") from err

        # Check for duplicate name
        for role in self._roles_cache.values():
            if role.name.lower() == name.lower():
                raise InvalidDataError(f"Role with name '{name}' already exists")

        role = Role(
            role_id=secrets.token_urlsafe(16),
            name=name,
            description=description,
            is_system=False,
            permissions=perm_scopes,
            created_at=utc(),
        )

        await self._store_role(role)
        self.logger.info(f"Created custom role: {name}")
        return role

    @api_command("rbac/role/update", required_role="admin")
    async def update_role(
        self,
        role_id: str,
        name: str | None = None,
        description: str | None = None,
        permissions: list[str] | None = None,
    ) -> Role:
        """
        Update a custom role (admin only). System roles cannot be modified.

        :param role_id: Role ID to update.
        :param name: New name (optional).
        :param description: New description (optional).
        :param permissions: New permissions list (optional).
        :return: Updated role.
        """
        role = self._roles_cache.get(role_id)
        if not role:
            raise InvalidDataError("Role not found")

        if role.is_system:
            raise InvalidDataError("Cannot modify system roles")

        # Update fields
        if name is not None:
            # Check for duplicate name
            for existing_role in self._roles_cache.values():
                if existing_role.role_id != role_id and existing_role.name.lower() == name.lower():
                    raise InvalidDataError(f"Role with name '{name}' already exists")
            role.name = name

        if description is not None:
            role.description = description

        if permissions is not None:
            perm_scopes = []
            for perm in permissions:
                try:
                    perm_scopes.append(PermissionScope(perm))
                except ValueError as err:
                    raise InvalidDataError(f"Invalid permission: {perm}") from err
            role.permissions = perm_scopes

        await self._store_role(role)
        self.logger.info(f"Updated role: {role.name}")
        return role

    @api_command("rbac/role/delete", required_role="admin")
    async def delete_role(self, role_id: str) -> None:
        """
        Delete a custom role (admin only). System roles cannot be deleted.

        :param role_id: Role ID to delete.
        """
        role = self._roles_cache.get(role_id)
        if not role:
            raise InvalidDataError("Role not found")

        if role.is_system:
            raise InvalidDataError("Cannot delete system roles")

        # Remove role assignments
        await self.database.delete("rbac_user_roles", {"role_id": role_id})

        # Delete role
        await self.database.delete("rbac_roles", {"role_id": role_id})

        # Remove from cache
        del self._roles_cache[role_id]

        self.logger.info(f"Deleted role: {role.name}")

    async def get_user_roles(self, user: User) -> list[Role]:
        """
        Get all roles assigned to a user.

        :param user: User object.
        :return: List of roles.
        """
        # Legacy support: if user has old UserRole, map to RBAC role
        if hasattr(user, "role") and isinstance(user.role, UserRole):
            legacy_role_id = "admin" if user.role == UserRole.ADMIN else "user"
            if legacy_role_id in self._roles_cache:
                return [self._roles_cache[legacy_role_id]]

        # Get roles from database
        rows = await self.database.get_rows("rbac_user_roles", {"user_id": user.user_id})
        roles = []
        for row in rows:
            if role := self._roles_cache.get(row["role_id"]):
                roles.append(role)

        # If no roles assigned, assign default user role
        if not roles and "user" in self._roles_cache:
            await self.assign_role_to_user(user.user_id, "user")
            return [self._roles_cache["user"]]

        return roles

    @api_command("rbac/user/roles")
    async def get_my_roles(self) -> list[dict[str, Any]]:
        """
        Get current user's roles.

        :return: List of roles.
        """
        user = get_current_user()
        if not user:
            raise AuthenticationRequired("Not authenticated")

        roles = await self.get_user_roles(user)
        return [role.to_dict() for role in roles]

    @api_command("rbac/user/roles/list", required_role="admin")
    async def get_user_roles_admin(self, user_id: str) -> list[dict[str, Any]]:
        """
        Get roles for a specific user (admin only).

        :param user_id: User ID.
        :return: List of roles.
        """
        user = await self.auth_manager.get_user(user_id)
        if not user:
            raise InvalidDataError("User not found")

        roles = await self.get_user_roles(user)
        return [role.to_dict() for role in roles]

    @api_command("rbac/user/role/assign", required_role="admin")
    async def assign_role_to_user(self, user_id: str, role_id: str) -> None:
        """
        Assign a role to a user (admin only).

        :param user_id: User ID.
        :param role_id: Role ID to assign.
        """
        # Verify user exists
        user = await self.auth_manager.get_user(user_id)
        if not user:
            raise InvalidDataError("User not found")

        # Verify role exists
        if role_id not in self._roles_cache:
            raise InvalidDataError("Role not found")

        # Check if already assigned
        existing = await self.database.get_row(
            "rbac_user_roles", {"user_id": user_id, "role_id": role_id}
        )
        if existing:
            return  # Already assigned

        # Assign role
        await self.database.insert(
            "rbac_user_roles",
            {
                "user_id": user_id,
                "role_id": role_id,
                "assigned_at": utc().isoformat(),
            },
        )

        self.logger.info(f"Assigned role '{role_id}' to user '{user.username}'")

    @api_command("rbac/user/role/revoke", required_role="admin")
    async def revoke_role_from_user(self, user_id: str, role_id: str) -> None:
        """
        Revoke a role from a user (admin only).

        :param user_id: User ID.
        :param role_id: Role ID to revoke.
        """
        await self.database.delete("rbac_user_roles", {"user_id": user_id, "role_id": role_id})

        self.logger.info(f"Revoked role '{role_id}' from user '{user_id}'")

    async def user_has_permission_async(
        self, user: User, permission: PermissionScope | str
    ) -> bool:
        """
        Check if user has a specific permission (async version).

        :param user: User object.
        :param permission: Permission to check.
        :return: True if user has permission.
        """
        if isinstance(permission, str):
            try:
                permission = PermissionScope(permission)
            except ValueError:
                return False

        # Get user roles
        roles = await self.get_user_roles(user)

        # Check if any role grants the permission
        return any(role.has_permission(permission) for role in roles)

    def user_has_permission(self, user: User, permission: PermissionScope | str) -> bool:
        """
        Check if user has a specific permission (sync wrapper for backwards compatibility).

        :param user: User object.
        :param permission: Permission to check.
        :return: True if user has permission.
        """
        if isinstance(permission, str):
            try:
                permission = PermissionScope(permission)
            except ValueError:
                return False

        # Fall back to legacy role check for sync context
        # For sync context, we can't properly check RBAC roles
        # This is a limitation - decorator should use async version
        return hasattr(user, "role") and user.role == UserRole.ADMIN

    @api_command("rbac/permissions")
    async def list_permissions(self) -> list[dict[str, Any]]:
        """
        Get all available permissions.

        :return: List of permission information.
        """
        permissions = []
        for perm in PermissionScope:
            permissions.append(
                {
                    "scope": perm.value,
                    "name": perm.name.replace("_", " ").title(),
                    "description": self._get_permission_description(perm),
                }
            )
        return permissions

    def _get_permission_description(self, perm: PermissionScope) -> str:
        """Get human-readable description for permission."""
        descriptions = {
            PermissionScope.PLAYER_CONTROL: "Control playback (play, pause, stop, next, previous)",
            PermissionScope.PLAYER_VOLUME: "Adjust player volume",
            PermissionScope.PLAYER_QUEUE: "Manage playback queue",
            PermissionScope.PLAYER_POWER: "Power players on/off",
            PermissionScope.PLAYER_VIEW: "View player status and information",
            PermissionScope.LIBRARY_READ: "Browse and search the music library",
            PermissionScope.LIBRARY_WRITE: "Add and edit library items",
            PermissionScope.LIBRARY_DELETE: "Delete library items",
            PermissionScope.PLAYLIST_READ: "View playlists",
            PermissionScope.PLAYLIST_WRITE: "Create and edit playlists",
            PermissionScope.PLAYLIST_DELETE: "Delete playlists",
            PermissionScope.PROVIDER_VIEW: "View music provider status",
            PermissionScope.PROVIDER_MANAGE: "Configure music providers",
            PermissionScope.SYSTEM_SETTINGS: "Modify system settings",
            PermissionScope.SYSTEM_ADMIN: "Full administrative access",
            PermissionScope.USER_READ: "View user accounts",
            PermissionScope.USER_WRITE: "Create and edit user accounts",
            PermissionScope.USER_DELETE: "Delete user accounts",
        }
        return descriptions.get(perm, "No description available")
