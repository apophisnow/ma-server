# RBAC Implementation Guide for Music Assistant

## Overview

This RBAC (Role-Based Access Control) implementation provides fine-grained permission management for Music Assistant, allowing you to control what actions users can perform.

## Architecture

### Components

1. **Permission Scopes** (`PermissionScope` enum)
   - Granular permissions like `PLAYER_CONTROL`, `LIBRARY_WRITE`, etc.
   - Organized by category (player, library, playlist, system, user)

2. **Roles** (`Role` class)
   - Named collections of permissions
   - Can be system-defined or custom
   - Supports permission inheritance via `SYSTEM_ADMIN`

3. **RBAC Manager** (`RBACManager` class)
   - Manages roles and assignments
   - Provides API commands for role management
   - Handles permission checking

4. **Permission Decorator** (`@require_permission`)
   - Simple decorator for API commands
   - Supports single or multiple permissions
   - Configurable logic (ALL or ANY)

## Installation Steps

### 1. Add Models to `music_assistant_models/auth.py`

Add the content from the "RBAC Models Extension" artifact to your models file. This includes:
- `PermissionScope` enum
- `Permission` dataclass
- `Role` dataclass
- `DEFAULT_ROLES` dictionary

### 2. Create RBAC Manager

Create `music_assistant/controllers/webserver/rbac.py` with the "RBAC Manager Implementation" artifact content.

### 3. Add Permission Decorator

Create `music_assistant/helpers/rbac.py` with the "RBAC Permission Decorator" artifact content, or add it to your existing `helpers/api.py`.

### 4. Integrate with AuthenticationManager

In `music_assistant/controllers/webserver/auth.py`:

```python
# Add import
from music_assistant.controllers.webserver.rbac import RBACManager

# In __init__ method
def __init__(self, webserver: WebserverController) -> None:
    # ... existing code ...
    self.rbac: RBACManager = None  # type: ignore[assignment]

# In setup method (after database setup)
async def setup(self) -> None:
    # ... existing database setup ...
    
    # Setup RBAC
    self.rbac = RBACManager(self)
    await self.rbac.setup()
    
    # ... rest of setup ...
```

## Usage Examples

### Basic Permission Check (Decorator)

```python
from music_assistant_models.auth import PermissionScope
from music_assistant.helpers.rbac import require_permission

@api_command("player/play")
@require_permission(PermissionScope.PLAYER_CONTROL)
async def play(self, player_id: str) -> None:
    """Start playback - requires PLAYER_CONTROL permission."""
    # Your code here
    pass
```

### Multiple Permissions (ALL required)

```python
@api_command("library/modify")
@require_permission(PermissionScope.LIBRARY_READ, PermissionScope.LIBRARY_WRITE)
async def modify_item(self, item_id: str, data: dict) -> None:
    """Modify library item - requires both READ and WRITE."""
    pass
```

### Multiple Permissions (ANY required)

```python
@api_command("player/advanced")
@require_permission(
    PermissionScope.PLAYER_POWER,
    PermissionScope.SYSTEM_ADMIN,
    any_permission=True
)
async def advanced_control(self, player_id: str) -> None:
    """Advanced control - requires PLAYER_POWER OR SYSTEM_ADMIN."""
    pass
```

### Manual Permission Check

```python
from music_assistant.controllers.webserver.helpers.auth_middleware import get_current_user

async def complex_operation(self):
    user = get_current_user()
    
    # Check permission manually
    if not self.mass.auth.rbac.user_has_permission(user, PermissionScope.LIBRARY_WRITE):
        raise InsufficientPermissions("Cannot modify library")
    
    # Proceed with operation
    await self._do_modification()
```

## Default Roles

The system includes 4 pre-defined roles:

### 1. Administrator (`admin`)
- **Permissions**: `SYSTEM_ADMIN` (grants all permissions)
- **Use case**: Full system access
- **Cannot be**: Modified or deleted

### 2. Standard User (`user`)
- **Permissions**:
  - All player control (control, volume, queue, view)
  - Library read
  - Playlist read/write
  - Provider view
- **Use case**: Regular users who can play music and manage playlists
- **Cannot be**: Modified or deleted

### 3. Guest (`guest`)
- **Permissions**:
  - Player view
  - Library read
  - Playlist read
- **Use case**: Read-only access for guests
- **Cannot be**: Modified or deleted

### 4. DJ (`dj`)
- **Permissions**:
  - All player control
  - Library read
  - Playlist read
- **Use case**: Party/event DJs who control playback without library access
- **Cannot be**: Modified or deleted

## API Commands

### Role Management

```python
# List all roles
await mass.auth.rbac.list_roles()

# Get specific role (admin only)
await mass.auth.rbac.get_role("role_id")

# Create custom role (admin only)
await mass.auth.rbac.create_role(
    name="Custom DJ",
    description="DJ with playlist editing",
    permissions=[
        "player.control",
        "player.volume",
        "player.queue",
        "playlist.write"
    ]
)

# Update role (admin only, custom roles only)
await mass.auth.rbac.update_role(
    role_id="custom_role_id",
    name="Updated Name",
    permissions=["player.control", "library.read"]
)

# Delete role (admin only, custom roles only)
await mass.auth.rbac.delete_role("custom_role_id")
```

### User Role Assignment

```python
# Get current user's roles
await mass.auth.rbac.get_my_roles()

# Get another user's roles (admin only)
await mass.auth.rbac.get_user_roles_admin("user_id")

# Assign role to user (admin only)
await mass.auth.rbac.assign_role_to_user("user_id", "role_id")

# Revoke role from user (admin only)
await mass.auth.rbac.revoke_role_from_user("user_id", "role_id")
```

### Permission Information

```python
# List all available permissions
await mass.auth.rbac.list_permissions()
```

## Migration from Legacy UserRole

The RBAC system maintains backward compatibility with the existing `UserRole` enum:

- Users with `UserRole.ADMIN` → Automatically mapped to `admin` role
- Users with `UserRole.USER` → Automatically mapped to `user` role
- New users → Automatically assigned `user` role

No database migration is required. The system will work alongside existing authentication.

## Permission Scopes Reference

### Player Permissions
- `PLAYER_CONTROL` - Play, pause, stop, next, previous
- `PLAYER_VOLUME` - Adjust volume
- `PLAYER_QUEUE` - Manage queue
- `PLAYER_POWER` - Power on/off
- `PLAYER_VIEW` - View status

### Library Permissions
- `LIBRARY_READ` - Browse and search
- `LIBRARY_WRITE` - Add/edit items
- `LIBRARY_DELETE` - Delete items

### Playlist Permissions
- `PLAYLIST_READ` - View playlists
- `PLAYLIST_WRITE` - Create/edit playlists
- `PLAYLIST_DELETE` - Delete playlists

### Provider Permissions
- `PROVIDER_VIEW` - View provider status
- `PROVIDER_MANAGE` - Configure providers

### System Permissions
- `SYSTEM_SETTINGS` - Modify settings
- `SYSTEM_ADMIN` - Full admin access (grants all permissions)

### User Permissions
- `USER_READ` - View users
- `USER_WRITE` - Create/edit users
- `USER_DELETE` - Delete users

## Best Practices

### 1. Use Decorators for API Commands
```python
# Good
@api_command("player/play")
@require_permission(PermissionScope.PLAYER_CONTROL)
async def play(self, player_id: str) -> None:
    pass

# Avoid manual checks in every function
```

### 2. Choose Appropriate Granularity
```python
# Too granular - hard to manage
PLAYER_PLAY, PLAYER_PAUSE, PLAYER_STOP, PLAYER_NEXT, PLAYER_PREV

# Good - logical grouping
PLAYER_CONTROL
```

### 3. Use ANY logic for Admin Overrides
```python
@require_permission(
    PermissionScope.SPECIFIC_PERMISSION,
    PermissionScope.SYSTEM_ADMIN,
    any_permission=True
)
```

### 4. Document Permission Requirements
```python
@api_command("library/add")
@require_permission(PermissionScope.LIBRARY_WRITE)
async def add_item(self, uri: str) -> None:
    """
    Add item to library.
    
    Requires: LIBRARY_WRITE permission
    """
    pass
```

## Security Considerations

1. **System Admin Permission** - `SYSTEM_ADMIN` grants ALL permissions. Use sparingly.

2. **Role Assignment** - Only admins can assign roles. Protect admin accounts.

3. **Custom Roles** - System roles cannot be modified or deleted to prevent privilege escalation.

4. **Token Revocation** - Revoking a user's roles doesn't invalidate existing tokens. Consider token management.

5. **Default Permissions** - New users get the `user` role by default. Adjust if needed for your use case.

## Testing

```python
# Test permission checking
user = await auth_manager.get_user("user_id")
roles = await rbac_manager.get_user_roles(user)

for role in roles:
    assert role.has_permission(PermissionScope.PLAYER_CONTROL)

# Test role assignment
await rbac_manager.assign_role_to_user("user_id", "dj")
roles = await rbac_manager.get_user_roles(user)
assert any(r.role_id == "dj" for r in roles)

# Test API access
try:
    await some_protected_api_command()
except InsufficientPermissions:
    print("User lacks required permission")
```

## Troubleshooting

### Permission Denied Errors
- Check user's assigned roles: `get_my_roles()`
- Verify role has required permission: `list_roles()`
- Ensure decorator is applied correctly
- Check for typos in permission scope values

### Roles Not Persisting
- Verify database connection
- Check for transaction commits
- Review error logs

### Legacy UserRole Not Working
- Ensure backward compatibility mapping is active
- Users should automatically get RBAC roles based on UserRole

## Future Enhancements

Potential additions:
1. **Resource-level permissions** - Per-player, per-playlist permissions
2. **Time-based permissions** - Temporary access grants
3. **Permission groups** - Bundle related permissions
4. **Audit logging** - Track permission checks and role changes
5. **UI for role management** - Visual role/permission editor