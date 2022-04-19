from typing import Union

from vivarium.core.process import Process
from vivarium.core.types import State, Update

from model.reaction_network import ReactionNetwork
from sim.fba_gd import FbaGd, ProductionObjective


class FbaProcess(Process):
    """A Vivarium Process simulating a ReactionNetwork via gradient-descent FBA."""

    defaults = {
        'reactions': [],
        'drivers': {},
        'boundaries': [],
        'pid_kp': 0.5,
        'pid_ki': 0.0,
        'pid_kd': 0.0,
    }

    def __init__(self, config):
        # Super __init__ sets self.parameters from defaults + config
        super().__init__(config)

        self.network = ReactionNetwork(self.parameters['reactions'])
        self.drivers = self.parameters['drivers']
        self.boundaries = set(self.parameters['boundaries']) | self.drivers.keys()  # Drivers are also boundaries.
        self.pid_kp = self.parameters['pid_kp']
        self.pid_ki = self.parameters['pid_ki']
        self.pid_kd = self.parameters['pid_kd']

        # Set up the FBA problem. Everything not declared as a driver or boundary is an intermediate.
        self.intermediates = [met for met in self.network.reactants() if met not in self.boundaries]
        self.fba = FbaGd(self.network, self.intermediates, {
            'drivers': ProductionObjective(self.network, {met: 0.0 for met, target in self.drivers.items()})
        })

    def ports_schema(self):
        return {
            'metabolites': {
                met.id: {'_default': 0.0, '_emit': True} for met in self.boundaries
            },
            'fluxes': {
                rxn.id: {'_default': 0.0, '_updater': 'set', '_emit': True} for rxn in self.network.reactions()
            },
            'pid_data': {
                'last': {met.id: {'_default': 0.0, '_updater': 'set', '_emit': False} for met in self.drivers},
                'cum_error': {met.id: {'_default': 0.0, '_emit': False} for met in self.drivers},
            }
            # 'pid_last': {met.id: {'_default': 0.0, '_updater': 'set', '_emit': False} for met in self.drivers},
            # 'pid_cum_error': {met.id: {'_default': 0.0, '_emit': False} for met in self.drivers},
        }

    def next_update(self, time_step: Union[float, int], states: State) -> Update:
        # PID controller logic to calculate target production rates.
        errors = {}
        targets = {}
        for met, target in self.drivers.items():
            current = states['metabolites'][met.id]
            delta = current - states['pid_data']['last'][met.id]
            cum_error = states['pid_data']['cum_error'][met.id]
            errors[met] = target - current
            targets[met] = errors[met] * self.pid_kp + cum_error * self.pid_ki + delta * self.pid_kd

        self.fba.update_params({'drivers': targets})

        # Solve the problem and return updates
        soln = self.fba.solve()

        # Report rates of change for boundary metabolites, and flux for all reactions.
        dmdts = {}
        for met, dmdt in self.network.reactant_values(soln.dmdt).items():
            if met in self.boundaries:
                dmdts[met.id] = dmdt
        velocities = {}
        for rxn, velocity in self.network.reaction_values(soln.velocities).items():
            velocities[rxn.id] = velocity

        return {
            'metabolites': dmdts,
            'fluxes': velocities,
            'pid_data': {
                'last': {met.id: states['metabolites'][met.id] for met in self.drivers},
                'cum_error': {met.id: error for met, error in errors.items()}
            }
            # 'pid_last': {met.id: states['metabolites'][met.id] for met in self.drivers},
            # 'pid_cum_error': {met.id: error for met, error in errors.items()},
        }