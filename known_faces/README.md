
# Employee reference photos

Place one clear, front-facing photo per employee in this directory. The filename
(without extension) becomes the employee name used throughout the system:

```
known_faces/
├── Alice.png
├── Bob.jpg
└── Carol.webp
```

Supported formats: `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.tiff`.

## Do not commit these files

The images in this folder are **biometric personal data**. `.gitignore` excludes
them (this README is the only tracked file here) and they must stay that way —
committing a face to a public repository is a permanent disclosure that cannot be
undone by deleting the file later.

The same applies to `screenshots/`, which holds breach evidence of identifiable
people. Faces in those screenshots are blurred automatically before they are
written to disk, but the folder is still excluded from version control.
