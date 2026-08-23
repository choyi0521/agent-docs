# Scripted Blender path

Use Blender when the explanation depends on 3D space, coordinate frames,
camera frusta, occlusion, culling, geometry, lighting, or a physical mechanism.

## Commit the scene recipe

The reproducible authority is a Python script, optionally accompanied by a
useful `.blend` file:

```powershell
blender --background --factory-startup --python build.py -- `
  --output figure.png
```

For an audited product bundle, this `build.py` is the committed build authority,
not merely a scene experiment. It must normalize the canonical `figure.png` and
emit `figure.html` with its visible caption; alternatively, use a normal Python
`build.py` wrapper that invokes a separately named Blender scene script.

Create named objects, collections, materials, camera, lights, and render
settings explicitly. Prefer Blender's data API over UI-context-dependent
operators. When an operator is unavoidable, establish its mode, selection, and
active object first.

Pin the Blender version when exact pixels matter. Set resolution, color
management, render engine, samples, seed, world, camera transform, and output
format in the recipe. Do not inherit a user's startup file.

## Explain rather than decorate

- Coordinate figure: show origin, axes, parent transform, and one traced point.
- Culling figure: show camera frustum, visible volume, rejected objects, and the
  exact test or hierarchy level responsible for rejection.
- Spatial pipeline: use ghosted stages or small multiples rather than a pile of
  arrows in one view.
- Hidden geometry: use a cutaway or depth-separated comparison.

Use orthographic projection when perspective would distort the relation being
explained. Use perspective when view-dependent scale or occlusion is the claim.

## Verify

Run the headless recipe, inspect the image, and retain any diagnostic angle or
wireframe render needed to prove orientation. Confirm labels and overlays match
the final camera and are not manually aligned to a stale render.
