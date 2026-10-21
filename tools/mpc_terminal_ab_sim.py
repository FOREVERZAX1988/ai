"""Deterministic closed-loop A/B harness for the longitudinal MPC.

Three scenes, stepped at DT_MDL with a 0.5 s response lag:
  follow   : steady 20 m/s lead, ego starts 40 m behind the desired gap
  slowdown : lead applies -3 m/s^2 at t=20 s while ego is 25 m behind
  approach : ego at 15 m/s with a stationary lead 60 m ahead

Output is JSON so two solver builds can be diffed numerically.
"""
import json
from types import SimpleNamespace as NS

import numpy as np

from openpilot.cereal import log
from openpilot.common.realtime import DT_MDL as DT
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N, get_accel_from_plan
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import LongitudinalMpc, T_IDXS as T_IDXS_MPC
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.sunnypilot.selfdrive.controls.lib.e2e_lead_gap.tests.helpers import desired_gap

STANDARD = log.LongitudinalPersonality.standard
LAG = 0.5
CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]
T_MPC = np.asarray(T_IDXS_MPC)


def run(v_ego0, gap0, v_lead0, a_lead_fn, seconds):
  mpc = LongitudinalMpc(dt=DT)
  v, gap, v_lead, a_applied, prev = v_ego0, gap0, v_lead0, 0., 0.
  rows = []
  for i in range(int(round(seconds / DT))):
    t = i * DT
    a_lead = a_lead_fn(t)
    lead = NS(present=True, dRel=gap, vLead=v_lead, aLeadK=a_lead, aLeadTau=0.3, modelProb=1., radar=False)
    mpc.set_weights(True, personality=STANDARD)
    mpc.set_cur_state(v, prev)
    mpc.update(NS(leadOne=lead, leadTwo=NS(present=False)), personality=STANDARD)
    a_cmd = float(get_accel_from_plan(np.interp(CONTROL_N_T_IDX, T_MPC, mpc.v_solution),
                                      np.interp(CONTROL_N_T_IDX, T_MPC, mpc.a_solution), CONTROL_N_T_IDX, action_t=0.41))
    prev = a_cmd
    a_applied += DT / LAG * (a_cmd - a_applied)
    v = max(0., v + a_applied * DT)
    v_lead = max(0., v_lead + a_lead * DT)
    gap += (v_lead - v) * DT
    rows.append((t, gap, v, v_lead, a_cmd))
  tr = np.asarray(rows)
  return dict(
    steps=int(tr.shape[0]),
    a_sum=round(float(tr[:, 4].sum()), 6),
    a_min=round(float(tr[:, 4].min()), 6),
    a_max=round(float(tr[:, 4].max()), 6),
    a_rms=round(float(np.sqrt((tr[:, 4] ** 2).mean())), 6),
    gap_min=round(float(tr[:, 1].min()), 4),
    gap_end=round(float(tr[:, 1][-1]), 4),
    v_end=round(float(tr[:, 2][-1]), 4),
    v_lead_end=round(float(tr[:, 3][-1]), 4),
    first_3s_a=[round(float(x), 4) for x in tr[:61:20, 4]],
    last_3s_a=[round(float(x), 4) for x in tr[-61::20, 4]],
    trace=[round(float(x), 5) for x in tr[::40, 4]],
  )


out = {
  'follow': run(20., desired_gap(20., 20., STANDARD) + 40., 20., lambda t: 0., 60.),
  'slowdown': run(20., 25., 20., lambda t: (-3.0 if t >= 20. else 0.), 45.),
  'approach': run(15., 60., 0., lambda t: 0., 45.),
}
print(json.dumps(out, indent=1, sort_keys=True))
