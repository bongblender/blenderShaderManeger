# Blender Shader Manager

A lightweight Blender add-on (v5.1+) to save, organize, and instantly apply node-based shaders using JSON or ZIP files. It acts like a cassette system for your materials, allowing you to easily reuse them across projects.

## Features
* **JSON & ZIP Export:** Save node trees as lightweight JSON files, or pack them alongside their image textures into ZIP archives.
* **Full Node Support:** Accurately saves and restores node links, custom properties, Color Ramps, and RGB Curves.
* **Category Management:** Organize your shader library into custom subfolders directly from the UI.
* **Smart Import:** Detects missing texture, value, or color inputs and prompts you for them when applying a saved shader.

## Installation
1. Download the add-on as a `.py` file.
2. In Blender, navigate to **Edit > Preferences > Add-ons**.
3. Click the downward arrow in the top right, select **Install from Disk...**, and choose the downloaded file.
4. Check the box next to **Material: Blender Shader Manager** to enable it.

## Usage
1. Open the 3D Viewport and press `N` to open the Sidebar.
2. Navigate to the **Shaders** tab.
3. **Setup:** Choose a **Library Folder** on your computer where your shaders will be stored.
4. **Save:** Select an object with an active material, type a name in the text box, and click **Save as JSON** or **Pack as ZIP**.
5. **Organize:** Use the **Create Category** tool to make subfolders for better organization.
6. **Apply:** Select a category, pick a shader from the dropdown, and click **Apply Shader** to assign it to the active object.
