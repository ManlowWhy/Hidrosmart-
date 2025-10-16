// 1. Clase ZonaRiego

class ZonaRiego {
private:
  const int sensorPin;         
  const char* nombre;          
  int rawWet;                  
  int rawDry;                  

public:
  //constructor: necesita el pin del sensor y los valores raw
  ZonaRiego(const char* n, int sPin, int rWet, int rDry)
    : nombre(n), sensorPin(sPin), rawWet(rWet), rawDry(rDry) {
  }

  // metodo para leer y convertir la humedad a porcentaje
  int getHumedad() {
    int rawValue = analogRead(sensorPin);
    // Mapeo: rawDry (0%) a rawWet (100%)
    int percentage = map(rawValue, rawDry, rawWet, 0, 100);
    return constrain(percentage, 0, 100);
  }
};


//
//
// 2. Definiciones globales y los objectos

// Umbrales brutos del sensor (ajustá estos valores si es necesario)
const int RAW_WET = 210; // ~100% de humedad (valor analógico bajo)
const int RAW_DRY = 510; // ~0% de humedad (valor analógico alto)

// Pin único para el relé de la bomba
const int PIN_BOMBA = 5; 

// instancia de las tres zonas con los pines analogicos
// ZonaRiego(Nombre, Pin_Sensor, Raw_Wet, Raw_Dry)
ZonaRiego zonaFrontal("Frente", A0, RAW_WET, RAW_DRY);
ZonaRiego zonaTrasera("Trasera", A1, RAW_WET, RAW_DRY);
ZonaRiego zonaInterna("Interna", A2, RAW_WET, RAW_DRY);

//
//
// 3. estas son las funciones del arudino
void setup() {
  // aqui se inicializa la comu serial a 9600 baudios (NO CAMBIARLO sino jode el script de python)
  Serial.begin(9600);
  pinMode(PIN_BOMBA, OUTPUT); 
  digitalWrite(PIN_BOMBA, LOW); // la bomba inicia apagada
  Serial.println("\n--- Arduino listo para la comunicacion serial (Cerebro en PC) ---");
}

void loop() {
  
  // 1. OBTENER ESTADOS ACTUALES DE HUMEDAD
  int h1 = zonaFrontal.getHumedad();
  int h2 = zonaTrasera.getHumedad();
  int h3 = zonaInterna.getHumedad();
  
  // 2. ENVIAR DATOS A PYTHON: Humedad de las 3 zonas
  // El formato es simple para que Python lo pueda leer: H1:35|H2:40|H3:30
  Serial.print("H1:"); Serial.print(h1);
  Serial.print("|H2:"); Serial.print(h2);
  Serial.print("|H3:"); Serial.print(h3);
  Serial.println(); // Salto de línea para marcar el final del mensaje

  // 3. RECIBIR COMANDO DE PYTHON: Comando de 3 caracteres (ej. "100" o "000")
  // El comando representa: [Zona1_Riego][Zona2_Riego][Zona3_Riego]
  // '1' = Necesita riego (Python decidió encender)
  // '0' = No necesita riego (Python decidió apagar)
  
  if (Serial.available() >= 3) {
    char c1 = Serial.read(); // Estado Zona 1
    char c2 = Serial.read(); // Estado Zona 2
    char c3 = Serial.read(); // Estado Zona 3

    // limpia buffer por si python envió más de 3 bytes
    while(Serial.available() > 0) {
      Serial.read();
    }
    
    // 4. La bomba se enciende si cualquier zona tiene el comando 1
    if (c1 == '1' || c2 == '1' || c3 == '1') {
      digitalWrite(PIN_BOMBA, HIGH);
    } else {
      digitalWrite(PIN_BOMBA, LOW);
    }
  }

  // este delay nos ayuda para que el script de python lleve el ritmo
  delay(100); 
}