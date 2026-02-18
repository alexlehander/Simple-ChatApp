# gunicorn_conf.py
import eventlet
import warnings
# 1. Silenciar la advertencia de que Eventlet es viejo (Es solo ruido)
warnings.filterwarnings("ignore", category=DeprecationWarning, module="eventlet")
# 2. Parchear aquí mismo para ganar la carrera contra Gunicorn
eventlet.monkey_patch()
# 3. Configuración del Worker
worker_class = 'eventlet'
workers = 1
bind = '0.0.0.0:8080'