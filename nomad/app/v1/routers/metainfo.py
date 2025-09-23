#
# Copyright The NOMAD Authors.
#
# This file is part of NOMAD. See https://nomad-lab.eu for further info.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import datetime
from enum import Enum

from fastapi import APIRouter, HTTPException, Path, status
from mongoengine import DateTimeField, DictField, Document, ListField, StringField
from pydantic import BaseModel, Field

from nomad.app.v1.models import HTTPExceptionModel
from nomad.app.v1.utils import create_responses
from nomad.metainfo import Package
from nomad.utils import get_logger, strip

logger = get_logger(__name__)


class PackageDefinition(Document):
    snapshot_package_id = StringField(
        primary_key=True, regex=r'^\w{40}$', required=True
    )
    date_created = DateTimeField(default=datetime.datetime.now)
    entry_id = StringField(required=True)
    upload_id = StringField(required=True)
    qualified_name = StringField(required=True)
    package_definition = DictField(required=True)
    snapshot_section_ids = ListField(StringField(regex=r'^\w{40}$'), default=None)

    meta = {'indexes': ['snapshot_section_ids']}

    @classmethod
    def create_new(cls, package: Package, **kwargs):
        if package is None:
            return

        fields: dict = dict(
            entry_id=package.entry_id,
            upload_id=package.upload_id,
            qualified_name=package.qualified_name(),
            package_definition=package.m_to_dict(**(dict(with_def_id=True) | kwargs)),
            snapshot_section_ids=[
                section.definition_id for section in package.section_definitions
            ],
            date_created=datetime.datetime.now(),
        )

        target = cls.objects(snapshot_package_id=package.definition_id)

        if target.count() > 0:
            target.update_one(**{f'set__{k}': v for k, v in fields.items()})
        else:
            cls(snapshot_package_id=package.definition_id, **fields).save()

    @classmethod
    def get_by(cls, snapshot_id: str):
        packages = cls.objects(snapshot_section_ids=snapshot_id)

        if packages.count() == 0:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail='Package not found. The given section definition is not contained in any packages.',
            )

        result = packages.first().to_mongo().to_dict()
        result['snapshot_package_id'] = result.pop('_id')

        return result


#
# FastAPI router for the metainfo API.
#


router = APIRouter()


class APITag(str, Enum):
    DEFAULT = 'metainfo'


_bad_definition_response = (
    status.HTTP_404_NOT_FOUND,
    {
        'model': HTTPExceptionModel,
        'description': strip(
            """Package not found. The given section definition is not contained in any packages."""
        ),
    },
)

_not_authorized_to_upload = (
    status.HTTP_401_UNAUTHORIZED,
    {
        'model': HTTPExceptionModel,
        'description': strip("""Unauthorized. No credentials provided."""),
    },
)


class PackageDefinitionResponse(BaseModel):
    entry_id: str | None = Field(
        None, description='The entry ID of the upload that contains the package.'
    )
    upload_id: str | None = Field(
        None, description='The upload ID of the upload that contains the package.'
    )
    snapshot_package_id: str | None = Field(
        None, description='The sha1 based 40-digit long unique ID for the package.'
    )
    snapshot_section_id: str | None = Field(
        None, description='The section definition ID to be used to retrieve package.'
    )
    snapshot_section_ids: list | None = Field(
        None, description='A list of section unique IDs defined in this package.'
    )
    data: dict | None = Field(
        None, description='The JSON representation of the package.'
    )


@router.get(
    '/{section_definition_id}',
    tags=[APITag.DEFAULT],
    summary='Get the definition of package that contains the target ID based section definition.',
    response_model=PackageDefinitionResponse,
    responses=create_responses(_bad_definition_response),
    response_model_exclude_unset=True,
    response_model_exclude_none=True,
)
async def get_package_definition(
    section_definition_id: str = Path(
        ...,
        regex=r'^\w{40}$',
        description='The section definition id to be used to retrieve package.',
    ),
):
    """
    Retrieve the package that contains the target section.
    """
    mongo_package = PackageDefinition.get_by(section_definition_id)

    return PackageDefinitionResponse(
        entry_id=mongo_package['entry_id'],
        upload_id=mongo_package['upload_id'],
        snapshot_package_id=mongo_package['snapshot_package_id'],
        snapshot_section_id=section_definition_id,
        snapshot_section_ids=mongo_package['snapshot_section_ids'],
        data=mongo_package['package_definition'],
    )
