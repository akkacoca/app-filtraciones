import os
import requests
import json
from datetime import datetime
import schedule  
import time

# docker build -t my-api-filtraciones .

# region FUNCIONES

def realizar_busqueda(domain):
        
    # Crear carpeta para resultados si no existe
    folder_path = os.path.join('result', domain)  # Crea la carpeta result/{domain}
        
    # Limitar a 2 archivos, eliminando el más antiguo si hay más de 2
    archivos = sorted(os.listdir(folder_path), reverse=True)  # Ordenamos por fecha (descendente)

    # Comprobar los resultados obtenidos
    comprobar_resultados(folder_path, archivos[1], archivos[0])  


def comprobar_resultados(folder_path, archivo_antiguo, archivo_nuevo):
    """
    Compara los enlaces (link) entre el archivo JSON anterior y el nuevo para ver si hay cambios.
    Si hay cambios, notifica con un mensaje detallado.
    """
    # Leer el archivo antiguo
    path_antiguo = os.path.join(folder_path, archivo_antiguo)
    with open(path_antiguo, 'r') as file:
        antiguo_data = json.load(file)
    
    # Leer el archivo nuevo
    path_nuevo = os.path.join(folder_path, archivo_nuevo)
    with open(path_nuevo, 'r') as file:
        nuevo_data = json.load(file)
    
    # Obtener solo los links de los resultados
    links_antiguos = [result['link'] for result in antiguo_data.get('organic_results', [])]
    links_nuevos = [result['link'] for result in nuevo_data.get('organic_results', [])]
    
    # Comparar los links
    nuevos_links = set(links_nuevos) - set(links_antiguos)  # Enlaces que están en el nuevo pero no en el antiguo
    links_eliminados = set(links_antiguos) - set(links_nuevos)  # Enlaces que estaban en el antiguo pero no en el nuevo
    
    # Si no hay cambios, informar de que no hubo cambios
    if not nuevos_links and not links_eliminados:
        print("No hay cambios en los enlaces de los resultados.")
        return
    
    # Informar sobre los nuevos enlaces
    if nuevos_links:
        print("\n¡Nuevos enlaces detectados!")
        for link in nuevos_links:
            print(f"  - Nuevo enlace: {link}")
    
    # Informar sobre los enlaces eliminados
    if links_eliminados:
        print("\n¡Enlaces eliminados detectados!")
        for link in links_eliminados:
            print(f"  - Enlace eliminado: {link}")
    
    enviar_correo_emailjs(("\n".join(nuevos_links)), "\n".join(links_eliminados))
    

def enviar_correo_emailjs(new_link, removed_link, ):
    with open('email_api.json', 'r') as file:
        email_api_data = json.load(file)
    
    # URL de la API de EmailJS
    url = "https://api.emailjs.com/api/v1.0/email/send"
    
    # Datos para el correo
    data = {
        "service_id": email_api_data["service_id"],  # Reemplaza con tu Service ID de EmailJS
        "template_id": email_api_data["template_id"],  # Reemplaza con tu Template ID de EmailJS
        "user_id": email_api_data["user_id"],  # Reemplaza con tu User ID de EmailJS
        "template_params": {
            "new_link": new_link,
            "removed_link": removed_link,
            "email": email_api_data["email"],
        }
    }
    # Hacer la solicitud POST a la API de EmailJS
    response = requests.post(url, json=data)
    
    # Verificar si el correo fue enviado correctamente
    if response.status_code == 200:
        print("Correo enviado exitosamente!")
    else:
        print(f"Error al enviar correo: {response.text}")

# end region FUNCIONES

# region MAIN   

realizar_busqueda('atalantago.com')
    
# end region MAIN
