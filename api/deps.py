from fastapi import Request

def get_catalog(request: Request):
    return request.app.state.catalog

def get_jobs(request: Request):
    return request.app.state.jobs

def get_auth(request: Request):
    return request.app.state.auth