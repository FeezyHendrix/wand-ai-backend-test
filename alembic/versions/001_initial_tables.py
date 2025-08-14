"""Initial database tables

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create documents table
    op.create_table('documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('file_type', sa.String(length=50), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('raw_content', sa.Text(), nullable=True),
        sa.Column('doc_metadata', sa.JSON(), nullable=True),
        sa.Column('is_processed', sa.Boolean(), nullable=True),
        sa.Column('processing_status', sa.String(length=50), nullable=True),
        sa.Column('processing_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('content_hash')
    )

    # Create document_chunks table
    op.create_table('document_chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('start_char', sa.Integer(), nullable=True),
        sa.Column('end_char', sa.Integer(), nullable=True),
        sa.Column('chunk_metadata', sa.JSON(), nullable=True),
        sa.Column('vector_id', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_documents_content_hash', 'documents', ['content_hash'], unique=True)
    op.create_index('ix_documents_processing_status', 'documents', ['processing_status'], unique=False)
    op.create_index('ix_document_chunks_document_id', 'document_chunks', ['document_id'], unique=False)
    op.create_index('ix_document_chunks_vector_id', 'document_chunks', ['vector_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_document_chunks_vector_id', table_name='document_chunks')
    op.drop_index('ix_document_chunks_document_id', table_name='document_chunks')
    op.drop_index('ix_documents_processing_status', table_name='documents')
    op.drop_index('ix_documents_content_hash', table_name='documents')
    op.drop_table('document_chunks')
    op.drop_table('documents')