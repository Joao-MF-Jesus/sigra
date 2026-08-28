from __future__ import annotations

from typing import Protocol

from app.integrated_gold.repository import (
    IntegratedGoldFilters,
    IntegratedGoldRepository,
    IntegratedGoldStorageError,
)
from app.integrated_gold.schemas import (
    IntegratedCostItem,
    IntegratedCostPage,
    IntegratedDatasetMetadata,
    IntegratedVehicleDetail,
)


class IntegratedGoldUnavailableError(RuntimeError):
    pass


class IntegratedVehicleNotFoundError(RuntimeError):
    pass


class IntegratedGoldReader(Protocol):
    def eligible_dataset(self): ...

    def list_costs(self, dataset_version, filters, **kwargs): ...


class IntegratedGoldService:
    def __init__(self, repository: IntegratedGoldReader):
        self._repository = repository

    def _dataset(self):
        try:
            dataset = self._repository.eligible_dataset()
        except IntegratedGoldStorageError as exc:
            raise IntegratedGoldUnavailableError(
                "eligible integrated Gold dataset is unavailable"
            ) from exc
        if dataset is None:
            raise IntegratedGoldUnavailableError(
                "no active and eligible integrated Gold dataset"
            )
        return dataset

    def metadata(self) -> IntegratedDatasetMetadata:
        return IntegratedDatasetMetadata.model_validate(dict(self._dataset()))

    def list_costs(
        self,
        filters: IntegratedGoldFilters,
        *,
        limit: int,
        offset: int,
        sort_by: str,
        sort_direction: str,
    ) -> IntegratedCostPage:
        dataset = self._dataset()
        try:
            rows, total = self._repository.list_costs(
                dataset["dataset_version"],
                filters,
                limit=limit,
                offset=offset,
                sort_by=sort_by,
                sort_direction=sort_direction,
            )
        except IntegratedGoldStorageError as exc:
            raise IntegratedGoldUnavailableError(
                "eligible integrated Gold dataset is unavailable"
            ) from exc
        return IntegratedCostPage(
            items=[IntegratedCostItem.model_validate(dict(row)) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
            dataset_version=str(dataset["dataset_version"]),
        )

    def vehicle(self, vehicle_sk: int) -> IntegratedVehicleDetail:
        page = self.list_costs(
            IntegratedGoldFilters(vehicle_sk=vehicle_sk),
            limit=100,
            offset=0,
            sort_by="vehicle_sk",
            sort_direction="asc",
        )
        if not page.items:
            raise IntegratedVehicleNotFoundError(
                "vehicle is not present in the eligible integrated Gold dataset"
            )
        first = page.items[0]
        return IntegratedVehicleDetail(
            dataset_version=page.dataset_version,
            vehicle_sk=first.vehicle_sk,
            brand_name=first.brand_name,
            model_name=first.model_name,
            version_name=first.version_name,
            model_year=first.model_year,
            scenarios=page.items,
        )


def service_for_session(session) -> IntegratedGoldService:
    return IntegratedGoldService(IntegratedGoldRepository(session))
