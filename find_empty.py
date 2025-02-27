import os

def find_empty_files(start_path='Ronan Jr'):
    empty_files = []
    
    for root, dirs, files in os.walk(start_path):
        for file in files:
            if file == '__init__.py':
                continue
                
            file_path = os.path.join(root, file)
            try:
                if os.path.getsize(file_path) == 0:
                    empty_files.append(file_path)
            except OSError:
                print(f"Couldn't access: {file_path}")
    
    return empty_files

if __name__ == '__main__':
    empty_files = find_empty_files()
    
    if empty_files:
        print("\nEmpty files found:")
        for file in empty_files:
            print(f"- {file}")
        print("\nTotal empty files:", len(empty_files))
    else:
        print("No empty files found")