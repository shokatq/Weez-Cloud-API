from flask import Flask, request, jsonify
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions, ContentSettings
from datetime import datetime, timedelta, timezone
import os
import mimetypes
from io import BytesIO
from PIL import Image

app = Flask(__name__)

# Azure Blob Storage Configuration
AZURE_STORAGE_CONNECTION_STRING = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
CONTAINER_NAME = "weez-cloud-data"
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)

# Helper function to get blob client
def get_blob_client(email, filename):
    blob_name = f"{email}/{filename}"
    return blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=blob_name)

def get_mime_type(filename):
    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        # Fallback for common file types
        ext = os.path.splitext(filename)[1].lower()
        mime_types = {
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.ppt': 'application/vnd.ms-powerpoint',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.pdf': 'application/pdf',
            '.txt': 'text/plain',
            '.csv': 'text/csv',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
        }
        mime_type = mime_types.get(ext, 'application/octet-stream')
    return mime_type

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        email = request.form['email']
        file = request.files['file']
        filename = file.filename
        blob_client = get_blob_client(email, filename)
        mime_type = get_mime_type(filename)
        
        # Use ContentSettings for proper content type handling
        content_settings = ContentSettings(content_type=mime_type)
        
        # Upload with ContentSettings
        blob_client.upload_blob(file, overwrite=True, content_settings=content_settings)
        
        # Store metadata
        blob_client.set_blob_metadata({
            "upload_date": datetime.now(timezone.utc).isoformat(),
            "starred": "false",
            "mime_type": mime_type
        })
        print(f"[upload_file] File {filename} uploaded successfully for {email}")
        return jsonify({"message": f"File {filename} uploaded successfully"}), 200
    except Exception as e:
        print(f"[upload_file] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/delete', methods=['POST'])
def delete_file():
    try:
        email = request.json['email']
        filename = request.json['filename']
        blob_client = get_blob_client(email, filename)
        blob_client.delete_blob()
        print(f"[delete_file] File {filename} deleted successfully for {email}")
        return jsonify({"message": f"File {filename} deleted successfully"}), 200
    except Exception as e:
        print(f"[delete_file] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/list', methods=['GET'])
def list_files():
    try:
        email = request.args.get('email')
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        blobs = container_client.list_blobs(name_starts_with=f"{email}/", include=['metadata'])
        file_list = [
            {
                "name": blob.name.split('/')[1],
                "size": blob.size,
                "upload_date": blob.metadata.get("upload_date", ""),
                "mime_type": blob.metadata.get("mime_type", get_mime_type(blob.name.split('/')[1])),
                "starred": blob.metadata.get("starred", "false") == "true"
            }
            for blob in blobs
        ]
        print(f"[list_files] Listed {len(file_list)} files for {email}")
        return jsonify({"files": file_list}), 200
    except Exception as e:
        print(f"[list_files] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/generate-sas', methods=['POST'])
def generate_sas():
    try:
        email = request.json['email']
        filename = request.json['filename']
        duration = int(request.json.get('duration', 1))
        blob_client = get_blob_client(email, filename)
        blob_properties = blob_client.get_blob_properties()
        mime_type = blob_properties.content_settings.content_type or get_mime_type(filename)
        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=CONTAINER_NAME,
            blob_name=f"{email}/{filename}",
            account_key=blob_service_client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=duration)
        )
        sas_url = f"{blob_client.url}?{sas_token}&_mime_type={mime_type}"
        print(f"[generate_sas] Generated SAS URL for {filename} with MIME type {mime_type}")
        return jsonify({"sas_url": sas_url, "mime_type": mime_type}), 200
    except Exception as e:
        print(f"[generate_sas] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/thumbnail', methods=['POST'])
def generate_thumbnail():
    try:
        email = request.json['email']
        filename = request.json['filename']
        blob_client = get_blob_client(email, filename)
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if mime_type.startswith('image'):
            blob_data = blob_client.download_blob().readall()
            img = Image.open(BytesIO(blob_data))
            img.thumbnail((100, 100))
            output = BytesIO()
            img.save(output, format="PNG")
            thumbnail_data = output.getvalue()
            sas_token = generate_blob_sas(
                account_name=blob_service_client.account_name,
                container_name=CONTAINER_NAME,
                blob_name=f"{email}/thumbnails/{filename}.png",
                account_key=blob_service_client.credential.account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(timezone.utc) + timedelta(hours=1)
            )
            thumbnail_client = get_blob_client(email, f"thumbnails/{filename}.png")
            thumbnail_client.upload_blob(thumbnail_data, overwrite=True)
            print(f"[generate_thumbnail] Thumbnail generated for {filename}")
            return jsonify({"thumbnail_url": f"{thumbnail_client.url}?{sas_token}"}), 200
        print(f"[generate_thumbnail] No thumbnail available for {filename}")
        return jsonify({"message": "No thumbnail available"}), 200
    except Exception as e:
        print(f"[generate_thumbnail] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/search', methods=['GET'])
def search_files():
    try:
        email = request.args.get('email')
        query = request.args.get('query', '').lower()
        type_filter = request.args.get('type', '')
        date_filter = request.args.get('date', '')
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        blobs = container_client.list_blobs(name_starts_with=f"{email}/", include=['metadata'])
        file_list = [
            {
                "name": blob.name.split('/')[1],
                "size": blob.size,
                "upload_date": blob.metadata.get("upload_date", ""),
                "mime_type": mimetypes.guess_type(blob.name.split('/')[1])[0] or "application/octet-stream",
                "starred": blob.metadata.get("starred", "false") == "true"
            }
            for blob in blobs
        ]
        filtered_files = [
            f for f in file_list
            if (query in f["name"].lower() or not query) and
               (type_filter in f["mime_type"] or not type_filter) and
               (date_filter in f["upload_date"] or not date_filter)
        ]
        print(f"[search_files] Found {len(filtered_files)} files matching query for {email}")
        return jsonify({"files": filtered_files}), 200
    except Exception as e:
        print(f"[search_files] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/star', methods=['POST'])
def star_file():
    try:
        email = request.json['email']
        filename = request.json['filename']
        starred = request.json['starred']
        print(f"[star_file] Updating starred status for {email}/{filename} to {starred}")
        blob_client = get_blob_client(email, filename)
        try:
            blob_properties = blob_client.get_blob_properties()
            print(f"[star_file] Blob found: {blob_properties.name}")
        except Exception as e:
            print(f"[star_file] Blob not found: {str(e)}")
            return jsonify({"error": f"File {filename} not found"}), 404
        metadata = blob_client.get_blob_metadata() or {}
        metadata["starred"] = "true" if starred else "false"
        blob_client.set_blob_metadata(metadata)
        print(f"[star_file] Starred status updated to {metadata['starred']}")
        return jsonify({"message": f"File {filename} starred status updated"}), 200
    except Exception as e:
        print(f"[star_file] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/storage-usage', methods=['GET'])
def storage_usage():
    try:
        email = request.args.get('email')
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        blobs = container_client.list_blobs(name_starts_with=f"{email}/")
        total_size = sum(blob.size for blob in blobs) / (1024 * 1024)
        print(f"[storage_usage] Calculated usage for {email}: {total_size} MB")
        return jsonify({"usage_mb": total_size}), 200
    except Exception as e:
        print(f"[storage_usage] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
