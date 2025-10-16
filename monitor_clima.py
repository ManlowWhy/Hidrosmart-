import serial
import time
from datetime import datetime, timedelta
import re 
import requests

#configuracion global API
API_KEY = "360c8f34092e4d7ebbfa16fc914080ba" 
CIUDAD = "Cartago"  
PAIS_CODIGO = "CRC" 
UMBRAL_LLUVIA = 0.70 # 70%

#configuracion de la comu serial
PUERTO_SERIAL = 'COM4' 
BAUD_RATE = 9600
TIEMPO_LOOP = 5 #Segundos entre chequeos principales

#configuracion de zonas de riego
#h es la humedad
#horario: [Hora_Inicio, Min_Inicio, Hora_Fin, Min_Fin, Frecuencia_Dias (0=off, 1=diario)]
ZONAS_CONFIG = {
    'H1': {'min': 35, 'max': 60, 'horario': [7, 0, 7, 15, 1], 'nombre': 'Frente'},
    'H2': {'min': 40, 'max': 70, 'horario': [21, 0, 22, 0, 3], 'nombre': 'Trasera'},
    'H3': {'min': 30, 'max': 50, 'horario': [0, 0, 0, 0, 0], 'nombre': 'Interna'}
}


#clases
class WeatherClient: #maneja las consultas a la api de weatherbit
    def __init__(self, api_key, city, country_code, rain_threshold):
        self.rain_threshold = rain_threshold
        self.weather_url = (
            f"https://api.weatherbit.io/v2.0/forecast/daily?"
            f"city={city}&country={country_code}&key={api_key}"
        )
        self.last_check_time = datetime.min
        self.is_raining_forecast = False
        self.check_interval = timedelta(hours=1) #1 hora entre consultas

    def check_for_rain_forecast(self): #consulta a la api si ha pasado el intervalo de tiempo y actualiza si se espera lluvia (probabilidad > umbral).
        now = datetime.now()
        if now - self.last_check_time < self.check_interval:
            return self.is_raining_forecast
        
        print("[CLIMA] Consultando a Weatherbit...")

        try:
            response = requests.get(self.weather_url)
            response.raise_for_status() 
            datos = response.json()
            
            #usa el pronostico del dia(indice 0)
            pronostico_hoy = datos['data'][0]
            #convierte 'pop' que es la Probability of Precipitation de porcentaje a decimal
            prob_lluvia = pronostico_hoy.get('pop', 0) / 100.0
            
            self.is_raining_forecast = (prob_lluvia > self.rain_threshold)
            self.last_check_time = now #actualiza el tiempo de la última consulta

            if self.is_raining_forecast:
                print(f"[CLIMA] Probabilidad de lluvia: {prob_lluvia:.2f} 🌧 Riego Bloqueado por lluvia.")
            else:
                print(f"[CLIMA] Probabilidad de Lluvia: {prob_lluvia:.2f} ☀️ Clima Despejado.")
            
            return self.is_raining_forecast

        except requests.exceptions.RequestException as e:
            print(f"[ERROR CLIMA] Falló la conexión con Weatherbit: {e}")
            return self.is_raining_forecast #si falla entonces que se use el ultimo estado que conocimos
        except (KeyError, IndexError):
            print("[ERROR CLIMA] Error al parsear la respuesta JSON de Weatherbit.")
            return self.is_raining_forecast #aqui igual

class IrrigationController: #clase principal que maneja la comu con el arduino y la logica de riego
    def __init__(self, port, baud_rate, zones_config, weather_client):
        self.zones_config = zones_config
        self.weather_client = weather_client
        self.regex_humedad = re.compile(r"H1:(\d+)\|H2:(\d+)\|H3:(\d+)")
        self.serial_port = None
        self.port = port
        self.baud_rate = baud_rate

    def _connect_serial(self): #aqui se intenta la conexion serial
        try:
            self.serial_port = serial.Serial(self.port, self.baud_rate, timeout=0.1)
            time.sleep(2) 
            print("----------------------------------------------------------------------")
            print(f"Cerebro ON. Conexión en {self.port}.")
            print("----------------------------------------------------------------------")
            return True
        except serial.SerialException as e:
            print(f"\n Error de conexión serial: {e}")
            print("Revisar que sea el puerto correcto y en el IDE de Arduino el Monitor Serial debe estar cerrado.")
            return False

    def _check_scheduler(self, now, zona_cfg): #revisa si la hora actual está dentro del horario
        h = zona_cfg['horario']
        frecuencia = h[4]
        
        #zona siempre apagada (frecuencia 0)
        if frecuencia == 0:
            return False
            
        #logica simplificada de la frecuencia
        if frecuencia > 1 and (now.day % frecuencia) != 1: 
            return False

        #convertir a minutos del día para comparar
        ahora_minutos = now.hour * 60 + now.minute
        inicio_minutos = h[0] * 60 + h[1]
        fin_minutos = h[2] * 60 + h[3]

        return inicio_minutos <= ahora_minutos < fin_minutos

    def _read_and_parse_humidity(self): #lee los datos del arduino y hace parsear
        if self.serial_port.in_waiting > 0:
            linea_serial = self.serial_port.readline().decode('utf-8').strip()
            match = self.regex_humedad.match(linea_serial)
            
            if match:
                return {
                    'H1': int(match.group(1)),
                    'H2': int(match.group(2)),
                    'H3': int(match.group(3))
                }
        return None

    def _determine_irrigation(self, now, humedades, va_a_llover): #logica de decision y devuelve comando de 3 carac
        #devuelve el comando de 3 caracteres y si la bomba debe estar encendida
        comando_final = ""
        bomba_on_flag = False

        print(f"\n[{now.strftime('%H:%M:%S')}] Humedad: H1:{humedades['H1']}% | H2:{humedades['H2']}% | H3:{humedades['H3']}%")

        for zona_id, cfg in self.zones_config.items():
            humedad_actual = humedades[zona_id]
            necesita_riego = False

            #aqui revisa el umbral minimo. la priorida es riego de emergencia
            if humedad_actual < cfg['min']:
                print(f"  [ALERTA] {cfg['nombre']}: HUMEDAD CRÍTICA ({humedad_actual}%). Riego de Emergencia ON.")
                necesita_riego = True
            
            else:
                #aqui es el que es programado
                programado_on = self._check_scheduler(now, cfg)

                if programado_on:
                    if va_a_llover:
                        #bloqueo por lluvia
                        print(f"  [{cfg['nombre']}] Riego cancelado. Lluvia detectada.")
                    elif humedad_actual > cfg['max']:
                        #bloqueo por humedad maxima
                        print(f"  [{cfg['nombre']}] Riego cancelado. Humedad ({humedad_actual}%) > Máx ({cfg['max']}%).")
                    else:
                        print(f"  [{cfg['nombre']}] Riego Programado OK.")
                        necesita_riego = True
            
            comando_final += '1' if necesita_riego else '0'
            if necesita_riego:
                bomba_on_flag = True
                
        return comando_final, bomba_on_flag


    def run(self): # este es el bucle principal del arduino
        if not self._connect_serial():
            return
        try:
            while True:
                now = datetime.now()

                #consulta clima. se autolimita por la logica interna de WeatherClient
                va_a_llover = self.weather_client.check_for_rain_forecast()

                #lee humedad
                humedades = self._read_and_parse_humidity()
                
                if humedades:
                    #decision principal
                    comando, bomba_on = self._determine_irrigation(now, humedades, va_a_llover)
                    
                    #aqui es donde encia comandos al arduino
                    self.serial_port.write(comando.encode('ascii'))
                    
                    estado_bomba = "ON" if bomba_on else "OFF"
                    print(f"  [COMANDO] Enviando '{comando}'. Bomba Maestra: {estado_bomba}")
                    print("-" * 70)
                    
                time.sleep(TIEMPO_LOOP) 

        except KeyboardInterrupt:
            print("\n\nPrograma de Python detenido.")
        finally:
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
                print("Conexión serial cerrada.")

#
#
#este es el punto de entrada
if __name__ == '__main__':
    #para inicial el api
    weather_client = WeatherClient(
        API_KEY, 
        CIUDAD, 
        PAIS_CODIGO, 
        UMBRAL_LLUVIA
    )
    
    #inia el control de nuestro riego
    controller = IrrigationController(
        PUERTO_SERIAL, 
        BAUD_RATE, 
        ZONAS_CONFIG, 
        weather_client
    )
    
    # hace que el controlador se ejecute
    controller.run()
