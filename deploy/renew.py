"""Hourly renewal entry point, no user-supplied commands or shared ACME account."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.system import Runner
from deploy.tls import renew

if __name__ == '__main__': renew(Runner('/var/log/gerstep-interactive/renew.log'))
