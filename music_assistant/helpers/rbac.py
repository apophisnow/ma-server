"""RBAC permission decorator for Music Assistant."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar

from music_assistant_models.auth import PermissionScope
from music_assistant_models.errors import InsufficientPermissions

if TYPE_CHECKING:
    from collections.abc import Awaitable

T = TypeVar("T")


def require_permission(
    *permissions: PermissionScope | str,
    any_permission: bool = False,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Require specific permissions for API commands.

    :param permissions: Required permission(s). Can be PermissionScope enum or string.
    :param any_permission: If True, user needs ANY of the permissions.
                          If False (default), user needs ALL permissions.

    Usage:
        @api_command("player/play")
        @require_permission(PermissionScope.PLAYER_CONTROL)
        async def play(self, player_id: str) -> None:
            ...

        @api_command("player/volume")
        @require_permission(PermissionScope.PLAYER_VOLUME, PermissionScope.PLAYER_CONTROL)
        async def set_volume(self, player_id: str, volume: int) -> None:
            ...

        @api_command("library/edit")
        @require_permission(
            PermissionScope.LIBRARY_WRITE,
            PermissionScope.SYSTEM_ADMIN,
            any_permission=True
        )
        async def edit_item(self, item_id: str) -> None:
            ...
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            # Import here to avoid circular imports
            from music_assistant.controllers.webserver.helpers.auth_middleware import (  # noqa: PLC0415
                get_current_user,
            )

            user = get_current_user()
            if not user:
                raise InsufficientPermissions("Authentication required")

            # Get RBAC manager from mass instance
            # Assumes first arg is 'self' with access to mass
            if args and hasattr(args[0], "mass"):
                mass = args[0].mass
                if hasattr(mass, "auth") and hasattr(mass.auth, "rbac"):
                    rbac_manager = mass.auth.rbac

                    # Check permissions using async version
                    if any_permission:
                        # User needs ANY of the specified permissions
                        has_permission = False
                        for perm in permissions:
                            if await rbac_manager.user_has_permission_async(user, perm):
                                has_permission = True
                                break
                    else:
                        # User needs ALL of the specified permissions
                        has_permission = True
                        for perm in permissions:
                            if not await rbac_manager.user_has_permission_async(user, perm):
                                has_permission = False
                                break

                    if not has_permission:
                        perm_names = [
                            p.value if isinstance(p, PermissionScope) else p for p in permissions
                        ]
                        if any_permission:
                            raise InsufficientPermissions(
                                f"Requires any of: {', '.join(perm_names)}"
                            )
                        raise InsufficientPermissions(f"Requires all of: {', '.join(perm_names)}")

            return await func(*args, **kwargs)

        return wrapper

    return decorator
