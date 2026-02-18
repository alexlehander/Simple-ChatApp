# gunicorn_conf.py
import gevent.monkey
gevent.monkey.patch_all()

worker_class = 'geventwebsocket.gunicorn.workers.GeventWebSocketWorker'
workers = 1
bind = '0.0.0.0:8080'