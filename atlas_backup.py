import os
import zipfile
import datetime
import subprocess
import sys

# Configuration
BACKUP_DIR = "/Users/yasser/backups"
SCRIPTS_DIR = "/Users/yasser/scripts"
HERMES_DIR = os.path.expanduser("~/.hermes/profiles/atlas")
GDRIVE_FOLDER = "Atlas_V2_Backups"

def create_zip():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"atlas_v2_backup_{timestamp}.zip"
    zip_path = os.path.join(BACKUP_DIR, zip_name)
    
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Backup Scripts
        for root, dirs, files in os.walk(SCRIPTS_DIR):
            for file in files:
                zipf.write(os.path.join(root, file), 
                           os.path.relpath(os.path.join(root, file), os.path.join(SCRIPTS_DIR, '..')))
        
        # Backup Hermes Profile (Skills, SOUL, etc.)
        for root, dirs, files in os.walk(HERMES_DIR):
            if "logs" in dirs:
                dirs.remove("logs") # Skip logs
            for file in files:
                zipf.write(os.path.join(root, file), 
                           os.path.relpath(os.path.join(root, file), os.path.join(HERMES_DIR, '..')))
                
    return zip_path

def upload_to_gdrive(file_path):
    # Ensure the folder exists in GDrive (gws doesn't have a direct 'mkdir -p' equivalent for drive, so we just upload)
    # We'll use gws drive files upload
    try:
        cmd = ["gws", "drive", "files", "upload", file_path, "--params", f'{{"name": "{os.path.basename(file_path)}"}}']
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Backup uploaded successfully: {os.path.basename(file_path)}")
        else:
            print(f"Error uploading backup: {result.stderr}")
    except Exception as e:
        print(f"Exception during upload: {e}")

if __name__ == "__main__":
    print(f"Starting Atlas V2 Backup at {datetime.datetime.now()}")
    zip_path = create_zip()
    print(f"Local backup created: {zip_path}")
    upload_to_gdrive(zip_path)
    print("Backup process complete.")
