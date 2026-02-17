# gunicorn_conf.py
import eventlet
# Parcheamos todo lo antes posible, antes de que cargue la app
eventlet.monkey_patch()

# Configuraciones básicas (opcional, ya las pasas por comando, pero aquí quedan ordenadas)
worker_class = 'eventlet'
workers = 1