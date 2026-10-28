import React, { useState } from "react";
import { resolveVehiclePhoto, vehiclePhotoLabel } from "./vehiclePhotoModel.js";
import "./vehiclePhotos.css";

function PhotoFrame({ photo, label, variant }) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const available = photo && !failed;
  return <figure className={`vehicle-photo vehicle-photo--${variant}`} data-photo-group={available ? photo.imageGroup : "unavailable"}>
    <div className={`vehicle-photo__frame${loaded && available ? " is-loaded" : ""}`}>
      {available && <img src={photo.variants[1].src}
        srcSet={photo.variants.map((image) => `${image.src} ${image.width}w`).join(", ")}
        sizes={variant === "comparison" ? "160px" : variant === "details" ? "(max-width: 640px) 90vw, 760px" : "(max-width: 640px) 90vw, 400px"}
        width={photo.variants[1].width} height={photo.variants[1].height}
        alt={`${photo.subject}; foto ilustrativa do modelo, não de uma unidade específica`}
        loading="lazy" decoding="async" onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />}
      {!available && <span className="vehicle-photo__fallback" role="img" aria-label={`Foto indisponível: ${label}`}>
        <span aria-hidden="true">—</span>Foto verificada indisponível
      </span>}
    </div>
    {available && <figcaption>
      <span>Foto ilustrativa do modelo. Versão, acabamento e mercado podem diferir.</span>
      {photo.correspondenceNote && <span>{photo.correspondenceNote}</span>}
      <span>Foto: {photo.artist} · <a href={photo.sourcePage} target="_blank" rel="noopener noreferrer">Fonte</a>
        {" · "}<a href={photo.licenseUrl} target="_blank" rel="noopener noreferrer">{photo.license}</a>
        {" · Redimensionada e convertida em WebP, sem recorte."}</span>
    </figcaption>}
  </figure>;
}

export default function VehiclePhoto({ vehicle, variant = "card" }) {
  const photo = resolveVehiclePhoto(vehicle);
  return <PhotoFrame key={photo?.imageGroup || "unavailable"} photo={photo}
    label={vehiclePhotoLabel(vehicle)} variant={variant} />;
}
