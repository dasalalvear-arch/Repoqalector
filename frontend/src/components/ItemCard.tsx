import { ArrowRightLeft, MapPin } from "lucide-react";

import { Item } from "../services/api";

type ItemCardProps = {
  item: Item;
  onRequest: (item: Item) => void;
  disabled?: boolean;
};

export function ItemCard({ item, onRequest, disabled }: ItemCardProps) {
  return (
    <article className="item-card">
      <div className="item-image">
        {item.images[0] ? <img src={item.images[0].image_url} alt="" /> : <ArrowRightLeft size={32} />}
        <span className="item-condition">{item.condition}</span>
      </div>
      <div className="item-body">
        <div className="item-meta">
          <span>{item.category.name}</span>
        </div>
        <h3>{item.title}</h3>
        <p>{item.description}</p>
        <div className="item-footer">
          <span>
            <MapPin size={15} />
            Campus UTEM
          </span>
          <button disabled={disabled || item.status !== "AVAILABLE"} onClick={() => onRequest(item)}>
            Solicitar
          </button>
        </div>
      </div>
    </article>
  );
}
