import { ChangeEvent, DragEvent, FormEvent, useEffect, useState } from "react";
import { Recycle, Sprout, UploadCloud, X } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import { api, Category, Item } from "../services/api";
import "../eco-theme.css";

const MAX_IMAGE_BYTES = 2 * 1024 * 1024; // 2 MB

export function PublishPage() {
  const navigate = useNavigate();
  const { id } = useParams();
  const editing = Boolean(id);
  const [categories, setCategories] = useState<Category[]>([]);
  const [item, setItem] = useState<Item | null>(null);
  const [image, setImage] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  useEffect(() => {
    api.get<Category[]>("/categories").then((response) => setCategories(response.data));
  }, []);

  useEffect(() => {
    if (!id) return;
    api.get<Item>(`/items/${id}`).then((response) => {
      setItem(response.data);
      setImage(response.data.images[0]?.image_url ?? null);
    });
  }, [id]);

  function handleFile(file: File | undefined) {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setImageError("El archivo debe ser una imagen.");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setImageError("La imagen supera el límite de 2 MB.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setImage(reader.result as string);
      setImageError(null);
    };
    reader.readAsDataURL(file);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragOver(false);
    handleFile(event.dataTransfer.files[0]);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {
      title: String(form.get("title")),
      description: String(form.get("description")),
      condition: String(form.get("condition")),
      category_id: Number(form.get("categoryId")),
      image_urls: image ? [image] : [],
    };

    if (editing) {
      await api.put(`/items/${id}`, payload);
      navigate("/mis-publicaciones", { replace: true });
    } else {
      await api.post("/items", payload);
      navigate("/", { replace: true, state: { notice: "Publicacion agregada." } });
    }
  }

  // Renderizamos el formulario solo cuando hay categorias y, si editamos, el
  // item ya cargo: asi los defaultValue (titulo, categoria...) quedan bien.
  const ready = categories.length > 0 && (!editing || item !== null);

  return (
    <section className="eco-form-page">
      <div className="eco-form-heading">
        <p className="eco-eyebrow" style={{ justifyContent: "center" }}>
          <Sprout size={20} /> {editing ? "Editar publicación" : "Nueva publicación"}
        </p>
        <h1>{editing ? "Actualiza tu publicación." : "Aporta al ecosistema académico."}</h1>
      </div>
      {!ready ? (
        <p className="muted">Cargando...</p>
      ) : (
        <form className="eco-form-stack" onSubmit={handleSubmit}>
          <label>
            Titulo
            <input
              name="title"
              required
              minLength={3}
              defaultValue={item?.title ?? ""}
              placeholder="Ej: Libro de Cálculo Multivariable"
            />
          </label>
          <label>
            Descripcion
            <textarea
              name="description"
              required
              minLength={10}
              rows={4}
              defaultValue={item?.description ?? ""}
              placeholder="Detalla el estado del ítem y por qué lo ofreces..."
            />
          </label>
          <div className="eco-form-grid">
            <label>
              Categoria
              <select name="categoryId" required defaultValue={item?.category.id ?? ""}>
                <option value="">Selecciona</option>
                {categories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Estado
              <input
                name="condition"
                required
                defaultValue={item?.condition ?? ""}
                placeholder="Ej: Usado, como nuevo..."
              />
            </label>
          </div>
          <div className="eco-field">
            <span>Imagen</span>
            {image ? (
              <div className="eco-dropzone-preview">
                <img src={image} alt="Vista previa" />
                <button type="button" onClick={() => setImage(null)} aria-label="Quitar imagen">
                  <X size={16} />
                </button>
              </div>
            ) : (
              <label
                className={`eco-dropzone${dragOver ? " is-dragover" : ""}`}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
              >
                <UploadCloud size={28} />
                <span>Arrastra una imagen o haz clic para subir</span>
                <input
                  type="file"
                  accept="image/*"
                  hidden
                  onChange={(event: ChangeEvent<HTMLInputElement>) => handleFile(event.target.files?.[0])}
                />
              </label>
            )}
            {imageError && <span className="eco-form-error">{imageError}</span>}
          </div>
          <button className="eco-btn-submit" type="submit">
            <Recycle size={20} />
            {editing ? "Guardar cambios" : "Publicar"}
          </button>
        </form>
      )}
    </section>
  );
}
