import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image
import piexif
import logging
import traceback
import io
import os
import requests
import base64


# Configure logging
logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("road_distress_app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ImgBB Image Upload Function
def upload_to_imgbb(image_file):
    """
    Upload an image to ImgBB and return the direct view URL
    
    :param image_file: File-like object of the image to upload
    :return: Direct view URL or None if upload fails
    """
    try:
        # Read the image file
        image_bytes = image_file.getvalue()
        
        # Encode the image to base64
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        # ImgBB API endpoint
        url = "https://api.imgbb.com/1/upload"
        
        # Parameters for the API request
        payload = {
            'key': '64869f569c72df2121fa2640ae4b3d1f',  # API key
            'image': base64_image
        }
        
        # Send POST request to ImgBB
        response = requests.post(url, data=payload)
        
        # Check if the upload was successful
        if response.status_code == 200:
            # Parse the JSON response
            result = response.json()
            
            # Return the direct view URL
            if result.get('success') and result.get('data'):
                return result['data']['display_url']
        
        # Log any errors
        logger.error(f"ImgBB upload failed. Status code: {response.status_code}")
        logger.error(f"Response: {response.text}")
        return None
    
    except Exception as e:
        logger.error(f"Error uploading to ImgBB: {e}")
        logger.error(traceback.format_exc())
        return None

def fetch_credentials_from_pantry():
    pantry_url = "https://getpantry.cloud/apiv1/pantry/2b37110f-cba8-408c-afe9-2e150aa440c1/basket/newBasket55"
    
    try:
        # Fetch data from Pantry
        response = requests.get(pantry_url)
        response.raise_for_status()  # Raise an exception for HTTP errors
        
        # Parse JSON content
        credentials_data = response.json()  # This will be a Python dictionary
        
        return credentials_data
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching data from Pantry: {e}")
        logger.error(f"Error fetching data from Pantry: {e}")
        return None

# Authenticate with Google Sheets using credentials from Pantry
def authenticate_google_sheets():
    try:
        # Fetch credentials from Pantry
        credentials_data = fetch_credentials_from_pantry()
        
        if not credentials_data:
            st.error("Failed to fetch credentials from Pantry")
            logger.error("Failed to fetch credentials from Pantry")
            return None

        # Define the scope for Google Sheets and Drive
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

        try:
            # Authenticate using the credentials from Pantry (google.oauth2 service_account Credentials)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_data, scopes=scope)
            
            # Authorize with gspread
            client = gspread.authorize(creds)
            
            # Log accessible spreadsheets (just for debugging purposes)
            spreadsheets = client.openall()
            logger.info("Accessible Spreadsheets:")
            for sheet in spreadsheets:
                logger.info(f"- {sheet.title}")
            
            return client
        except Exception as auth_error:
            st.error(f"Authentication Error: {auth_error}")
            logger.error(f"Authentication Error: {auth_error}")
            logger.error(traceback.format_exc())
            return None

    except Exception as e:
        st.error(f"Unexpected error: {e}")
        logger.error(f"Unexpected error: {e}")
        return None

def submit_to_google_sheets(client, data_to_submit):
    try:
        # List all accessible spreadsheets to verify
        spreadsheets = client.openall()
        logger.info(f"Accessible Spreadsheets: {[sheet.title for sheet in spreadsheets]}")
        
        # Try to open the sheet with exact matching
        try:
            sheet = client.open("Road Distress Data").sheet1
        except gspread.SpreadsheetNotFound:
            # If exact match fails, try partial match
            matching_sheets = [s for s in spreadsheets if "Road Distress" in s.title]
            
            if matching_sheets:
                sheet = matching_sheets[0].sheet1
                logger.info(f"Found matching sheet: {matching_sheets[0].title}")
            else:
                # If no matching sheet found, create a new one
                new_sheet = client.create("Road Distress Data")
                sheet = new_sheet.sheet1
                
                # Add headers
                headers = [
                    "Road Name", "District", "Road Type", "City", 
                    "Distress Type", "Severity", "Distress Length (m)", 
                    "Distress Width (m)", "Latitude", "Longitude", 
                    "Additional Notes", "Image URL"
                ]
                sheet.append_row(headers)
                logger.info("Created new spreadsheet with headers")
        
        # Prepare row data in the correct order
        row_data = [
            data_to_submit.get('Road Name', ''),
            data_to_submit.get('District', ''),
            data_to_submit.get('Road Type', ''),
            data_to_submit.get('City', ''),
            data_to_submit.get('Distress Type', ''),
            data_to_submit.get('Severity', ''),
            data_to_submit.get('Distress Length (m)', ''),
            data_to_submit.get('Distress Width (m)', ''),
            data_to_submit.get('Latitude', ''),
            data_to_submit.get('Longitude', ''),
            data_to_submit.get('Additional Notes', ''),
            data_to_submit.get('Image URL', '')
        ]
        
        # Append row to sheet
        sheet.append_row(row_data)
        logger.info("Data successfully submitted to Google Sheets")
        return True
    
    except Exception as e:
        logger.error(f"Google Sheets submission error: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        st.error(f"Error submitting to Google Sheets: {e}")
        return False

# GPS Coordinate Extraction Functions
def extract_gps_from_image(image):
    try:
        logger.info("Starting GPS extraction from image")
        
        img = Image.open(image)
        logger.info(f"Image opened successfully. Format: {img.format}, Mode: {img.mode}, Size: {img.size}")
        
        try:
            exif_dict = piexif.load(img.info.get('exif', b''))
            logger.info("EXIF data extracted successfully")
            
            logger.info("Available EXIF keys:")
            for ifd in exif_dict:
                logger.info(f"IFD: {ifd}")
                if ifd == 'GPS':
                    logger.info("GPS Data found:")
                    for tag, value in exif_dict[ifd].items():
                        logger.info(f"GPS Tag {tag}: {value}")
            
            if exif_dict.get('GPS'):
                gps_info = exif_dict['GPS']
                logger.info(f"Raw GPS Info: {gps_info}")
                return gps_info
            else:
                logger.warning("No GPS information found in EXIF data")
                return None
        
        except Exception as exif_error:
            logger.error("Error extracting EXIF data")
            logger.error(f"Error details: {str(exif_error)}")
            logger.error(traceback.format_exc())
            
            logger.info(f"Image info keys: {img.info.keys() if hasattr(img, 'info') else 'No info attribute'}")
        
        logger.warning("No GPS data could be extracted from the image")
        return None
    
    except Exception as e:
        logger.error("Critical error in GPS extraction")
        logger.error(f"Error: {str(e)}")
        logger.error(traceback.format_exc())
        
        logger.info(f"Image type: {type(image)}")
        logger.info(f"Image name: {getattr(image, 'name', 'Unknown')}")
        
        return None

def convert_gps_to_decimal(gps_coords):
    if not gps_coords:
        logger.warning("No GPS coordinates provided for conversion")
        return None, None
    
    try:
        logger.info("Starting GPS coordinate conversion")
        logger.info(f"Input GPS Coordinates: {gps_coords}")
        
        # Extract latitude
        lat = gps_coords.get(piexif.GPSIFD.GPSLatitude)
        lat_ref = gps_coords.get(piexif.GPSIFD.GPSLatitudeRef)
        
        # Extract longitude
        lon = gps_coords.get(piexif.GPSIFD.GPSLongitude)
        lon_ref = gps_coords.get(piexif.GPSIFD.GPSLongitudeRef)
        
        logger.info(f"Latitude: {lat}, Latitude Ref: {lat_ref}")
        logger.info(f"Longitude: {lon}, Longitude Ref: {lon_ref}")
        
        def convert_to_decimal(coordinate, reference):
            if not coordinate or not reference:
                return None
            
            try:
                degrees, minutes, seconds = coordinate
                decimal = degrees[0] + (minutes[0] / 60.0) + (seconds[0] / 3600.0)
                
                if reference in [b'S', b'W', 'S', 'W']:
                    decimal = -decimal
                
                return decimal
            except Exception as conv_error:
                logger.error(f"Coordinate conversion error: {conv_error}")
                return None
        
        # Convert coordinates
        lat_decimal = convert_to_decimal(lat, lat_ref)
        lon_decimal = convert_to_decimal(lon, lon_ref)
        
        logger.info(f"Converted Coordinates - Lat: {lat_decimal}, Lon: {lon_decimal}")
        
        return lat_decimal, lon_decimal
    
    except Exception as e:
        logger.error("Error converting GPS coordinates")
        logger.error(f"Error details: {str(e)}")
        logger.error(traceback.format_exc())
        
        return None, None

def get_gps_location():
    """
    Add a button to get GPS location with user guidance
    """
    st.subheader("GPS Location")
    
    # Informative text about location access
    st.info("""
    🌍 To capture your current location:
    1. Click "Get My Location" button
    2. Allow location access when prompted by your browser
    3. Ensure you have location services enabled on your device
    """)
    
    # Button to trigger location capture
    if st.button("📍 Get My Location"):
        # JavaScript to request and handle location
        location_script = """
        <script>
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                function(position) {
                    // Send coordinates back to Streamlit
                    window.parent.postMessage({
                        type: 'streamlit:location', 
                        latitude: position.coords.latitude, 
                        longitude: position.coords.longitude,
                        accuracy: position.coords.accuracy
                    }, '*');
                },
                function(error) {
                    // Handle location errors
                    let errorMessage = '';
                    switch(error.code) {
                        case error.PERMISSION_DENIED:
                            errorMessage = "Location access was denied. Please enable location permissions.";
                            break;
                        case error.POSITION_UNAVAILABLE:
                            errorMessage = "Location information is unavailable.";
                            break;
                        case error.TIMEOUT:
                            errorMessage = "Location request timed out.";
                            break;
                        default:
                            errorMessage = "An unknown error occurred.";
                    }
                    window.parent.postMessage({
                        type: 'streamlit:location-error', 
                        message: errorMessage
                    }, '*');
                },
                {
                    enableHighAccuracy: true,
                    timeout: 10000,
                    maximumAge: 0
                }
            );
        } else {
            window.parent.postMessage({
                type: 'streamlit:location-error', 
                message: 'Geolocation is not supported by this browser.'
            }, '*');
        }
        </script>
        """
        components.html(location_script, height=0)
        
        # Add message listener
        st.markdown("""
        <script>
        window.addEventListener('message', function(event) {
            if (event.data.type === 'streamlit:location') {
                Streamlit.setComponentValue({
                    'latitude': event.data.latitude,
                    'longitude': event.data.longitude,
                    'accuracy': event.data.accuracy
                });
            } else if (event.data.type === 'streamlit:location-error') {
                Streamlit.setComponentValue({
                    'error': event.data.message
                });
            }
        }, false);
        </script>
        """, unsafe_allow_html=True)

# Main Streamlit Application
def main():
    st.title("Road Distress Point Data Collection")
    
    # Create form sections
    st.header("Road Distress Information")
    
    # Location Details
    col1, col2 = st.columns(2)
    with col1:
        road_name = st.text_input("Road Name")
        district = st.text_input("District")
    
    with col2:
        road_type = st.selectbox("Road Type", [
            "Highway", 
            "Urban Road", 
            "Rural Road", 
            "State Highway", 
            "Other"
        ])
        city = st.text_input("City")
    
    # Distress Details
    col3, col4 = st.columns(2)
    with col3:
        distress_type = st.selectbox("Distress Type", [
            "Pothole", 
            "Crack", 
            "Rutting", 
            "Deformation", 
            "Other"
        ])
        severity = st.selectbox("Severity", [
            "Low", 
            "Medium", 
            "High", 
            "Critical"
        ])
    
    with col4:
        distress_length = st.number_input("Distress Length (meters)", min_value=0.0, step=0.1)
        distress_width = st.number_input("Distress Width (meters)", min_value=0.0, step=0.1)
    
    # Geolocation Options
    st.header("Geolocation")
    location_method = st.radio("Select Location Method", [
        "Manual Entry", 
        "Upload Image with GPS", 
        "Capture Image"
    ])
    
    latitude, longitude = None, None
    uploaded_image_url = None
    
    if location_method == "Manual Entry":
        col5, col6 = st.columns(2)
        with col5:
            latitude = st.number_input("Latitude", format="%.6f")
        with col6:
            longitude = st.number_input("Longitude", format="%.6f")
    
    elif location_method == "Upload Image with GPS":
        uploaded_image = st.file_uploader("Upload Image", type=['jpg', 'jpeg', 'png'])
        if uploaded_image:
            # Debug: Log uploaded image details
            #st.write(f"Uploaded Image Name: {uploaded_image.name}")
            #st.write(f"Uploaded Image Type: {uploaded_image.type}")
            #st.write(f"Uploaded Image Size: {uploaded_image.size} bytes")
            
            # Upload image to ImgBB
            uploaded_image_url = upload_to_imgbb(uploaded_image)
            if uploaded_image_url:
                st.success("Image successfully uploaded to ImgBB")
                #st.image(uploaded_image_url, caption="Uploaded Image")
            
            # Extract GPS from uploaded image with logging
            try:
                gps_data = extract_gps_from_image(uploaded_image)
                
                if gps_data:
                    latitude, longitude = convert_gps_to_decimal(gps_data)
                    if latitude and longitude:
                        st.success(f"GPS Coordinates Extracted: {latitude}, {longitude}")
                    else:
                        st.warning("Could not convert GPS coordinates")
                else:
                    st.warning("No GPS data found in the image")
            
            except Exception as e:
                st.error(f"Error processing image: {e}")
                # Log the full traceback
                st.error(traceback.format_exc())
    
    elif location_method == "Capture Image":
        captured_image = st.camera_input("Capture Image")
        if captured_image:
            # Debug: Log captured image details
            #st.write(f"Captured Image Name: {captured_image.name}")
            #st.write(f"Captured Image Type: {captured_image.type}")
            #st.write(f"Captured Image Size: {captured_image.size} bytes")
            st.success("Image captured successfully")
            
            # Upload image to ImgBB
            uploaded_image_url = upload_to_imgbb(captured_image)
            if uploaded_image_url:
                st.success("Image successfully uploaded to ImgBB")
            
            # Extract GPS from captured image
            try:
                get_gps_location()
        
                # Check if location was successfully retrieved
                location_data = st.session_state.get('location_details')
                if location_data and 'latitude' in location_data:
                    latitude = location_data['latitude']
                    longitude = location_data['longitude']
            
                    # Display retrieved location
                    st.success(f"Location Captured: {latitude}, {longitude}")
                elif location_data and 'error' in location_data:
                    # Show error if location retrieval failed
                    st.error(location_data['error'])
            
            except Exception as e:
                st.error(f"Error processing captured image: {e}")
                # Log the full traceback
                st.error(traceback.format_exc())
    
    # Additional Notes
    additional_notes = st.text_area("Additional Notes")
    
    # Submit Button
    if st.button("Submit Road Distress Data"):
        # Validate required fields
        if not all([road_name, district, road_type, distress_type, severity]):
            st.error("Please fill in all required fields")
            return
        
        # Prepare data for Google Sheets
        data_to_submit = {
            "Road Name": road_name,
            "District": district,
            "Road Type": road_type,
            "City": city,
            "Distress Type": distress_type,
            "Severity": severity,
            "Distress Length (m)": distress_length,
            "Distress Width (m)": distress_width,
            "Latitude": latitude,
            "Longitude": longitude,
            "Additional Notes": additional_notes,
            "Image URL": uploaded_image_url
        }
        
        # Log the data being submitted
        logger.info(f"Submitting data: {data_to_submit}")
        
        # Authenticate and submit to Google Sheets
        client = authenticate_google_sheets()
        if client:
            success = submit_to_google_sheets(client, data_to_submit)
            if success:
                st.success("Data successfully submitted to Google Sheets!")
            else:
                st.error("Failed to submit data to Google Sheets")

# Run the Streamlit app
if __name__ == "__main__":
    main()