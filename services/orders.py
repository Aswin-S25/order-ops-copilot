import uuid
from dataclasses import dataclass

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthContext
from db.models import Order, OrderItem, UserRole


@dataclass(frozen=True)
class OrderDetails:
    order: Order
    items: list[OrderItem]


def visible_orders(auth: AuthContext) -> Select[tuple[Order]]:
    query = select(Order).where(Order.tenant_id == auth.tenant_id)
    if auth.role is not UserRole.SUPPORT:
        query = query.where(Order.buyer_id == auth.user_id)
    return query


async def get_order(
    session: AsyncSession, auth: AuthContext, order_id: uuid.UUID
) -> OrderDetails | None:
    order = await session.scalar(visible_orders(auth).where(Order.id == order_id))
    if order is None:
        return None

    items = await session.scalars(
        select(OrderItem)
        .where(OrderItem.tenant_id == auth.tenant_id, OrderItem.order_id == order.id)
        .order_by(OrderItem.sku)
    )

    return OrderDetails(order=order, items=list(items))
