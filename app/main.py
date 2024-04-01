from fastapi import FastAPI, Request
import uvicorn
import httpx
from datetime import datetime, timezone
import base64

app = FastAPI()

CIN7_API_BASE_URL = "https://api.cin7.com/api/v1/SalesOrders"
CIN7_USERNAME = "user"
CIN7_PASSWORD = "pass"


def encode_basic_auth(username, password):
    credentials = f"{username}:{password}"
    token = base64.b64encode(credentials.encode())
    return f"Basic {token.decode('utf-8')}"


def get_oldest_created_at_date(shopify_orders):
    created_at_dates = [datetime.fromisoformat(
        order["createdAt"].rstrip("Z")) for order in shopify_orders]
    oldest_date = min(
        created_at_dates) if created_at_dates else datetime.now(timezone.utc)
    return oldest_date


async def fetch_cin7_orders(start_date: datetime, end_date: datetime):
    where_clause = f"where=CreatedDate>='{start_date.strftime('%Y-%m-%dT00:00:00Z')}' AND CreatedDate<='{end_date.strftime('%Y-%m-%dT23:59:59Z')}'"
    headers = {"Authorization": encode_basic_auth(
        CIN7_USERNAME, CIN7_PASSWORD)}
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{CIN7_API_BASE_URL}?{where_clause}", headers=headers)
    return response.json() if response.status_code == 200 else []


@app.post("/webhook/")
async def receive_webhook(request: Request):
    today = datetime.now(timezone.utc)

    if today.weekday() >= 5:
        return {"message": "Take the day off, it is the weekend."}

    payload = await request.json()
    shopify_orders = payload.get("orders", [])
    shopify_order_names = {order['name'] for order in shopify_orders}

    oldest_date = get_oldest_created_at_date(shopify_orders)

    cin7_orders = await fetch_cin7_orders(oldest_date, today)

    filtered_cin7_orders = [
        order for order in cin7_orders if order['reference'] in shopify_order_names]

    auth_headers = {"Authorization": encode_basic_auth(
        CIN7_USERNAME, CIN7_PASSWORD)}
    updates_made = 0
    for order in filtered_cin7_orders:
        if not order.get('dispatchedDate'):
            update_payload = {
                "dispatchedDate": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
            }
            response = await httpx.put(f"{CIN7_API_BASE_URL}/{order['id']}", headers=auth_headers, json=update_payload)
            if response.status_code in range(200, 300):
                updates_made += 1
            else:
                print(f"Failed to update order {order['id']}: {response.text}")

    return {"message": f"Processed with {updates_made} updates made."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
