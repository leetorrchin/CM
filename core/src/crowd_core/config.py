"""Physical constants used to compile a venue into a graph.

These are placeholders to calibrate against published crowd-dynamics data. They live in one
place so a scenario or sweep can change them later.
"""

# Walking speed on level ground, metres per second.
WALK_SPEED_MS = 1.4
# Speed multipliers by threshold kind (stairs and ramps slow people down).
SPEED_FACTOR = {"stairs": 0.45, "ramp": 0.8}
# People per second that can pass per metre of threshold width.
FLOW_PP_S_PER_M = 1.3
FLOW_FACTOR = {"stairs": 0.7, "ramp": 0.9}
# Maximum comfortable density used to derive a zone's capacity from its area, people per m^2.
DEFAULT_MAX_DENSITY_PP_M2 = 3.0
