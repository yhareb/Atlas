import os
import zipfile
import datetime
import subprocess
import sys
from atlas_notify import send_telegram

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
            if ".git" in dirs:
                dirs.remove(".git") # Skip git history in zip
            for file in files:
                if file.endswith(".db"): continue # Skip live DB in zip, handle separately if needed
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
    try:
        cmd = ["gws", "drive", "files", "upload", file_path, "--params", f'{{"name": "{os.path.basename(file_path)}"}}']
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Backup uploaded to GDrive: {os.path.basename(file_path)}")
        else:
            print(f"Error uploading to GDrive: {result.stderr}")
    except Exception as e:
        print(f"Exception during GDrive upload: {e}")

def git_push():
    print("Starting GitHub push...")
    try:
        # Add all changes
        subprocess.run(["git", "-C", SCRIPTS_DIR, "add", "."], check=True)
        # Commit with timestamp
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subprocess.run(["git", "-C", SCRIPTS_DIR, "commit", "-m", f"Automated Backup: {timestamp}"], capture_output=True)
        # Push to origin main
        result = subprocess.run(["git", "-C", SCRIPTS_DIR, "push", "origin", "main"], capture_output=True, text=True)
        if result.returncode == 0:
            print("GitHub push successful.")
        else:
            print(f"GitHub push failed: {result.stderr}")
    except Exception as e:
        print(f"Exception during GitHub push: {e}")

if __name__ == "__main__":
    print(f"Starting Atlas V2 Backup at {datetime.datetime.now()}")
    
    # 1. Local ZIP & GDrive Upload
    zip_path = create_zip()
    print(f"Local ZIP created: {zip_path}")
    upload_to_gdrive(zip_path)
    
    # 2. GitHub Push
    git_push()
    
    print("Backup process complete.")
    send_telegram(f"✅ Atlas V2 Backup complete\nLocal ZIP: {zip_path}", label="atlas_backup")
