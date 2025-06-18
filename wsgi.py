#!/usr/bin/env python3
"""WSGI entry point for production deployment."""

import sys
import os
from piper.http_server import main

# This will be used by WSGI servers like Gunicorn
# Example: gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app

if __name__ == "__main__":
    main()
