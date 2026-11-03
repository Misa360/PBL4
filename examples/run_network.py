"""Export a reproducible packet-network baseline without third-party packages."""

import argparse
import csv
import json
from pathlib import Path

from simulator.packet_simulation import PacketSimulation, SimulationConfig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=float, default=30)
    parser.add_argument('--load', type=float, default=40)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--policy', choices=['delay', 'energy_aware'], default='delay')
    args = parser.parse_args()
    simulation = PacketSimulation(SimulationConfig(
        duration_s=args.duration, packets_per_second=args.load,
        seed=args.seed, routing_policy=args.policy))
    history = []
    while simulation.time < simulation.config.duration_s - 1e-9:
        simulation.step()
        history.append(simulation.metrics())
    snapshot = simulation.snapshot()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    output.mkdir(exist_ok=True)
    label = f'{args.policy}_seed{args.seed}'
    (output / f'{label}.json').write_text(json.dumps(snapshot, indent=2, allow_nan=False), encoding='utf-8')
    with (output / f'{label}.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(history[0]))
        writer.writeheader()
        writer.writerows(history)
    print(json.dumps(snapshot['metrics'], indent=2, allow_nan=False))
    print(f'Results: {output}')


if __name__ == '__main__':
    main()
