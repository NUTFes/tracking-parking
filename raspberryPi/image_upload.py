import os

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive


class GoogleDriveFacade:
    
    def __init__(self, setting_path: str='settings.yaml'):
        gauth = GoogleAuth(setting_path)
        gauth.LocalWebserverAuth()

        self.drive = GoogleDrive(gauth)

    def create_folder(self, folder_name):
        ret = self.check_files(folder_name)
        if ret:
            folder = ret
            print(f"{folder['title']}: exists")
        else:   
            folder = self.drive.CreateFile(
                {
                    'title': folder_name,
                    'mimeType': 'application/vnd.google-apps.folder'
                }
            )
            folder.Upload()

        return folder

    def check_files(self, folder_name,):
        query = f'title = "{os.path.basename(folder_name)}"'

        list = self.drive.ListFile({'q': query}).GetList()
        if len(list)> 0:
            return list[0]
        return False

    def upload(self, 
               local_file_path: str,
               save_folder_name: str = 'sample',
               is_convert : bool=False,
        ):
        
        if save_folder_name:
            folder = self.create_folder(save_folder_name)
        
        file = self.drive.CreateFile(
            {
                'title':os.path.basename(local_file_path),
                'parents': [
                    {'id': folder["id"]}
                ]
            }
        )
        file.SetContentFile(local_file_path)
        file.Upload({'convert': is_convert})
        
        drive_url = f"https://drive.google.com/uc?id={str( file['id'] )}" 
        return drive_url
    
        
if __name__ == "__main__":
    g = GoogleDriveFacade()
    for i in range (3):
        for j in range (10000):
            local_file_path='./resorces/create_nuber_plates/img' + str(i) + "." + str(j) + '.jpg'
            print(local_file_path)
            g.upload(
                local_file_path='./resorces/create_nuber_plates/img' + str(i) + "." + str(j) + '.jpg',
                save_folder_name="test5",
                is_convert=False,
    )

