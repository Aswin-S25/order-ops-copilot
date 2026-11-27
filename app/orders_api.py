import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import AuthContext, Scope
from app.dependencies import DbSessionsDep, require_scope
from app.errors import NotFoundError
from db.models import OrderStatus
from db.session import tenant_session
from services import orders
from services.orders import OrderDetails

router = APIRouter(prefix="/orders", tags=["orders"])

OrderReader = Annotated[AuthContext, Depends(require_scope(Scope.ORDERS_READ))]


class Money(BaseModel):
    amount_minor: int
    currency: str


class OrderItemResponse(BaseModel):
    sku: str
    name: str
    quantity: int
    unit_price: Money


class OrderResponse(BaseModel):
    id: uuid.UUID
    order_number: str
    buyer_id: uuid.UUID
    seller_name: str
    status: OrderStatus
    total: Money
    placed_at: datetime
    delivered_at: datetime | None
    items: list[OrderItemResponse]

    @classmethod
    def from_details(cls, details: OrderDetails) -> "OrderResponse":
        order = details.order
        return cls(
            id=order.id,
            order_number=order.order_number,
            buyer_id=order.buyer_id,
            seller_name=order.seller_name,
            status=order.status,
            total=Money(amount_minor=order.total_minor, currency=order.currency),
            placed_at=order.placed_at,
            delivered_at=order.delivered_at,
            items=[
                OrderItemResponse(
                    sku=item.sku,
                    name=item.name,
                    quantity=item.quantity,
                    unit_price=Money(amount_minor=item.unit_price_minor, currency=item.currency),
                )
                for item in details.items
            ],
        )


@router.get("/{order_id}")
async def get_order(
    order_id: uuid.UUID, auth: OrderReader, sessions: DbSessionsDep
) -> OrderResponse:

    async with tenant_session(sessions, auth.tenant_id) as session:
        details = await orders.get_order(session, auth, order_id)
    if details is None:
        raise NotFoundError("Order not found.")
    return OrderResponse.from_details(details)
