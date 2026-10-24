"""Global simulation settings."""

# Share of people who have the app and report positions (0 to 1).
# 1.0 for early testing: everyone is tracked, so the planner does not need cameras or
# gate counts yet. Switch to ~0.25 (realistic target) once occupancy connectors and
# fusion exist. A scenario can override this with its own "app_adoption".
DEFAULT_APP_ADOPTION = 1.0
