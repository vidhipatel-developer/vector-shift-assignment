import os
import json
import httpx
import redis
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi import Request
from dotenv import load_dotenv

load_dotenv()

redis_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

# 1. Step 1: Start OAuth Flow
async def authorize_hubspot(user_id, org_id):
    client_id = os.getenv("HUBSPOT_CLIENT_ID")
    redirect_uri = "http://localhost:8000/oauth2callback/hubspot"
    scope = "crm.objects.contacts.read"

    return RedirectResponse(
        url=f"https://app.hubspot.com/oauth/authorize?client_id={client_id}&scope={scope}&redirect_uri={redirect_uri}&state={user_id}:{org_id}"
    )


# 2. Step 2: Handle Callback & Save Token
async def oauth2callback_hubspot(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")  # state = user_id:org_id

    if not code or not state:
        return JSONResponse({"error": "Missing code or state"}, status_code=400)

    user_id, org_id = state.split(":")

    response = await httpx.post(
        "https://api.hubapi.com/oauth/v1/token",
        data={
            "grant_type": "authorization_code",
            "client_id": os.getenv("HUBSPOT_CLIENT_ID"),
            "client_secret": os.getenv("HUBSPOT_CLIENT_SECRET"),
            "redirect_uri": "http://localhost:8000/oauth2callback/hubspot",
            "code": code,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    tokens = response.json()

    if "access_token" not in tokens:
        return JSONResponse({"error": "OAuth failed", "details": tokens}, status_code=400)

    key = f"hubspot:{user_id}:{org_id}"
    redis_client.set(key, json.dumps(tokens))

    return JSONResponse({"message": "HubSpot connected successfully"})


# 3. Step 3: Get Stored Credentials
async def get_hubspot_credentials(user_id, org_id):
    key = f"hubspot:{user_id}:{org_id}"
    tokens_json = redis_client.get(key)
    if not tokens_json:
        raise Exception("No credentials found for HubSpot")
    return json.loads(tokens_json)


# 4. Step 4: Fetch Items from HubSpot (Contacts)
async def get_items_hubspot(user_id, org_id):
    credentials = await get_hubspot_credentials(user_id, org_id)

    headers = {
        "Authorization": f"Bearer {credentials['access_token']}",
        "Content-Type": "application/json",
    }

    response = await httpx.get(
        "https://api.hubapi.com/crm/v3/objects/contacts",
        headers=headers,
    )

    data = response.json()
    return await create_integration_item_metadata_object(data["results"])


# 5. Step 5: Format Data for Frontend
async def create_integration_item_metadata_object(contacts):
    return [
        {
            "id": contact["id"],
            "name": contact["properties"].get("firstname", "") + " " + contact["properties"].get("lastname", ""),
            "email": contact["properties"].get("email", ""),
        }
        for contact in contacts
    ]
