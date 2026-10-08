#!/usr/bin/env python3
"""_sng_a_b_probe.py <mode> <route...>"""
import sys
sys.path.insert(0, '/data/openpilot')
sys.path.insert(0, '/data/openpilot/openpilot')
from openpilot.tools.lib.logreader import LogReader


def main():
  print("probe placeholder", sys.argv[1:])


if __name__ == "__main__":
  main()
