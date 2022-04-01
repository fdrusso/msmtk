from bson import ObjectId
from vivarium.core.composer import Composer
from vivarium.core.engine import Engine, pf
from vivarium.core.types import Processes

from kb import kb
from viv.process.fba_process import FbaProcess
from viv.process.util import Clamp, Drain

KB = kb.configure_kb()


class SimpleModel(Composer):
    def __init__(self, config: dict):
        super().__init__(config)

    def generate_processes(self, config: dict) -> Processes:
        processes = {}
        boundaries = {}
        if 'clamp' in config:
            processes['clamp'] = Clamp(**config['clamp'])
            boundaries.update({met: None for met in config['clamp']['targets']})
        if 'drain' in config:
            processes['drain'] = Drain(**config['drain'])
            boundaries.update({met: None for met in config['drain']['rates']})

        if 'drivers' in config:
            # May override existing met: None boundaries with target values
            for met, target in config['drivers'].items():
                boundaries[met] = target

        processes['process'] = FbaProcess(
            reactions=config.get('reactions'),
            boundaries=boundaries,
            gain=config.get('gain'),
        )

        return processes

    def generate_topology(self, config: dict):
        return {
            'process': {
                'metabolites': ('metabolites',),
                'fluxes': ('fluxes',),
            },
            'clamp': {
                'metabolites': ('metabolites',),
            },
            'drain': {
                'metabolites': ('metabolites',),
            }
        }


def main():
    glycolysis = KB.get(KB.pathways, ObjectId("61e21657e4819e9d1a81f65f"))
    reactions = glycolysis.steps + [KB.get(KB.reactions, 'pts.glc')]

    # Concentrations in mM, from http://book.bionumbers.org/what-are-the-concentrations-of-free-metabolites-in-cells
    concs = {KB.get(KB.compounds, met_id): conc for met_id, conc in {
        'accoa': 0.61,
        'adp': 0.55,
        'amp': 0.28,
        'atp': 9.6,
        'co2': 0.01,
        'coa': 1.4,
        'h+': 1e-7,
        'h2o': 55500,
        'nad.ox': 2.6,
        'nad.red': 0.083,
        'pi': 10.,
        'Glc.D.ext': 10.0,
    }.items()}
    acCoA = KB.get(KB.compounds, 'accoa')

    config = {
        'reactions': reactions,
        'drivers': {
            acCoA: concs[acCoA],
        },
        'clamp': {
            'targets': {met: conc for met, conc in concs.items() if met != acCoA}
        },
        'drain': {
            'rates': {
                acCoA: concs[acCoA] * 0.05,
            }
        },
        'gain': 0.5,
    }
    composer = SimpleModel(config)
    composite = composer.generate()

    sim = Engine(composite=composite,
                 initial_state={met.id: conc for met, conc in concs.items()},
                 )

    # run the engine
    total_time = 10
    sim.update(total_time)

    # get the data
    data = sim.emitter.get_data()

    print(pf(data))


if __name__ == '__main__':
    main()
