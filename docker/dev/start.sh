#!/bin/bash

pip install -r /opt/sfm-elk/requirements/dev.txt --upgrade

echo logging.quiet: true >> /opt/kibana/config/kibana.yml

/usr/local/bin/start.sh &

echo "Waiting for elk"
appdeps.py --port-wait mq:5672 --port-wait localhost:9200 --port-wait localhost:5601 --wait-secs 60
if [ "$?" = "1" ]; then
    echo "Problem with application dependencies."
    exit 1
fi

python elk_config_loader.py

python sfm_elk_loader.py mq $MQ_ENV_RABBITMQ_DEFAULT_USER $MQ_ENV_RABBITMQ_DEFAULT_PASS elk_loader_$HOSTNAME --debug=$DEBUG $* &

wait