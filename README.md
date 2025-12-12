# Proyecto de Filtración de Enlaces.
Este proyecto realiza búsquedas de dominios en Google utilizando la API de SerpAPI. Los resultados se guardan en archivos JSON y se envían notificaciones por correo electrónico en caso de detectar cambios. El proyecto está empaquetado en un contenedor Docker para facilitar su implementación y despliegue.
## Requisitos
Antes de empezar, asegúrate de tener las siguientes herramientas:

- Docker: Debes tener Docker instalado en tu sistema. Si no lo tienes, puedes instalarlo desde aquí
- SerpAPI: Crea una cuenta en SerpAPI y obtén tu API Key.
- EmailJS: Crea una cuenta en EmailJS y obtén las credenciales necesarias para configurar el envío de correos electrónicos.
## Pasos de Configuración y Ejecución
1. Configurar las credenciales de SerpAPI
Crea el archivo serpapi_api.json en el directorio raíz del proyecto con la siguiente estructura:
```JSON
{
  "api-url": "https://serpapi.com/search",
  "api-key": "TU_API_KEY_DE_SERPAPI",
}
```
2. Configurar las credenciales de EmailJS
Crea el archivo emailjs_api.json en el directorio raíz del proyecto con la siguiente estructura:
```JSON
{
    "service_id": "TU_SERVICE_ID_DE_EMAILJS", 
    "template_id": "TU_TEMPLATE_ID_DE_EMAILJS",  
    "user_id": "TU_USER_ID_DE_EMAILJS",  
    "email": "example@gmail.com"
}
```
3. Construir la imagen de Docker
A continuación, construye la imagen Docker del proyecto con el siguiente comando: `docker build -t my-api-filtraciones .`

4. Ejecutar el contenedor Docker

Una vez que la imagen se haya creado, ejecuta el contenedor en segundo plano con el siguiente comando:`docker run -d -p 5000:5000 my-api-filtraciones`