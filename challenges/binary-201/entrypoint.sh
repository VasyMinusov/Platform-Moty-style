#!/bin/sh
set -e
# Динамический флаг из оркестратора имеет приоритет.
echo "${FLAG:-flag{b0f_r3tw1n_4_sm00th_v1ct0ry}}" > /tmp/flag.txt
exec python server.py