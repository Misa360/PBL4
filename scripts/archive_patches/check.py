with open('earth_simulation.html', encoding='utf-8') as f:
    c = f.read()
checks = [
    ('createEarth import',   'import { createEarth }' in c),
    ('earthModule.update',   'earthModule.update(' in c),
    ('earthModule.surface',  'earthModule.surface.add' in c),
    ('latLonToVec3 alias',   'earthModule.latLonToVec3' in c),
    ('SUN_DIR defined',      'const SUN_DIR' in c),
    ('script type module',   'type="module"' in c),
    ('old buildEarth gone',  'function buildEarth()' not in c),
]
for name, ok in checks:
    print(f'  [{"OK" if ok else "FAIL"}] {name}')
