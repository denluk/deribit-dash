#!/bin/bash
cd /opt/workspace/deribit-dash
source venv/bin/activate
PYTHONPATH=/opt/workspace/deribit-dash/src streamlit run src/deribit_intel/app.py \
  --server.port 8501 --server.headless true
