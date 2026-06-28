"""Test api_server import."""
import sys
sys.path.insert(0, '/usr/local/lib/python3.11/site-packages')
try:
    import api_server
    print('api_server imported OK')
    print(f'Total routes: {len(api_server.app.routes)}')
    print('Routes with /trader:')
    for route in api_server.app.routes:
        if hasattr(route, 'path') and 'trader' in route.path:
            methods = list(route.methods) if hasattr(route, 'methods') and route.methods else ['?']
            print(f'  {methods} {route.path}')
except Exception as e:
    import traceback
    print(f'Error: {e}')
    traceback.print_exc()
