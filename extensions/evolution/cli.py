"""
Command-Line Interface for O0 Autonomous Continuous Self-Evolution Daemon.
Usage:
    python -m extensions.evolution.cli pulse [--goal "Optimize algorithm..."]
    python -m extensions.evolution.cli start [--interval 30] [--max-pulses 5]
    python -m extensions.evolution.cli status
"""

from __future__ import annotations

import argparse
import sys
import time

from extensions.evolution.autonomous_daemon import AutonomousEvolutionDaemon


def cmd_pulse(args: argparse.Namespace) -> None:
    daemon = AutonomousEvolutionDaemon()
    print(f"🧬 Triggering Single Autonomous Evolution Pulse...")
    if args.goal:
        print(f"   Target Goal: {args.goal}")
    res = daemon.step_pulse(target_goal=args.goal)

    icon = "🌟 PROMOTED" if res.status == "PROMOTED" else "↩️ REVERTED"
    print(f"\nResult: {icon}")
    print(f"• Pulse ID:      {res.pulse_id}")
    print(f"• Status:        {res.status}")
    print(f"• Baseline:      {res.baseline_score:.4f} -> Candidate: {res.candidate_score:.4f} (Delta: {res.delta_score:+.4f})")
    print(f"• Pareto Dominant: {res.pareto_dominant}")
    print(f"• Circuit Tier:  {res.circuit_tier}")
    print(f"• Signature:     {res.mutation_signature}")
    print(f"• Duration:      {res.duration_sec:.4f}s")
    print(f"• Report Path:   {res.report_path}")
    print(f"\nPersonal Reflection:")
    print(f"> {res.personal_note}")


def cmd_start(args: argparse.Namespace) -> None:
    interval = args.interval or 30.0
    max_pulses = args.max_pulses
    daemon = AutonomousEvolutionDaemon(pulse_interval_sec=interval)

    print(f"🚀 Launching Autonomous Continuous Self-Evolution Loop")
    print(f"   Heartbeat Cadence: every {interval}s | Max Pulses: {max_pulses or 'Unlimited'}")
    print("   Press Ctrl+C to safely disengage autonomous loop.\n")

    pulse_count = 0
    try:
        while True:
            pulse_count += 1
            print(f"--- [Pulse #{pulse_count}] {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
            res = daemon.step_pulse()
            status_icon = "🟢 PROMOTED" if res.status == "PROMOTED" else "⚪ REVERTED"
            print(f"Status: {status_icon} | Delta: {res.delta_score:+.4f} | Signature: {res.mutation_signature} | Latency: {res.duration_sec}s")

            if max_pulses and pulse_count >= max_pulses:
                print(f"\n🏁 Reached maximum pulse limit ({max_pulses}). Stopping loop.")
                break

            print(f"Sleeping {interval}s until next circadian pulse...\n")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n🛑 Disengaging autonomous evolution daemon cleanly.")
        print(f"Summary: Total Pulses: {daemon.total_pulses} | Promotions: {daemon.promotions_count} | Reversions: {daemon.reversions_count}")


def cmd_status(args: argparse.Namespace) -> None:
    daemon = AutonomousEvolutionDaemon()
    print("📊 O0 Autonomous Evolution Status Dashboard")
    print("-" * 65)
    print(f"Total Pulses Recorded:   {daemon.total_pulses}")
    print(f"Promotions (Win Rate):   {daemon.promotions_count}")
    print(f"Reversions:              {daemon.reversions_count}")
    print(f"Significance Epsilon:    {daemon.significance_epsilon}")
    print("-" * 65)


def main() -> None:
    parser = argparse.ArgumentParser(description="O0 Autonomous Self-Evolution Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # pulse
    p_pulse = subparsers.add_parser("pulse", help="Run a single evolution pulse")
    p_pulse.add_argument("--goal", type=str, default=None, help="Target optimization goal")

    # start
    p_start = subparsers.add_parser("start", help="Start continuous autonomous evolution loop")
    p_start.add_argument("--interval", type=float, default=30.0, help="Cadence in seconds between pulses")
    p_start.add_argument("--max-pulses", type=int, default=None, help="Stop after N pulses")

    # status
    subparsers.add_parser("status", help="View evolution engine metrics and pulse history")

    args = parser.parse_args()
    if args.command == "pulse":
        cmd_pulse(args)
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "status":
        cmd_status(args)


if __name__ == "__main__":
    main()
