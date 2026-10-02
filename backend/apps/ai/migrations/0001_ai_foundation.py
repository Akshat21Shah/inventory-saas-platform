"""ADR-058: AI usage records and product embeddings (pgvector)."""

import common.ids
import common.vectors
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from common.db_ops import EnableRLS


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('catalog', '0002_own_brand_cost_price'),
        ('platform', '0008_free_goods_flag'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunSQL("CREATE EXTENSION IF NOT EXISTS vector", migrations.RunSQL.noop),
        migrations.CreateModel(
            name='AiUsage',
            fields=[
                ('id', models.UUIDField(default=common.ids.uuid7, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('feature', models.CharField(choices=[('SEARCH_INDEX', 'Product search: indexing products'), ('SEARCH_QUERY', "Product search: a shop's search"), ('ASSISTANT', 'Data assistant')], max_length=14)),
                ('provider', models.CharField(max_length=20)),
                ('model', models.CharField(blank=True, default='', max_length=60)),
                ('units_in', models.PositiveIntegerField(default=0)),
                ('units_out', models.PositiveIntegerField(default=0)),
                ('duration_ms', models.PositiveIntegerField(default=0)),
                ('ok', models.BooleanField(default=True)),
                ('error', models.CharField(blank=True, default='', max_length=200)),
                ('created_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('tenant', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='platform.tenant')),
            ],
            options={
                'indexes': [models.Index(fields=['tenant', 'created_at'], name='ai_usage_tenant_idx')],
            },
        ),
        migrations.CreateModel(
            name='ProductEmbedding',
            fields=[
                ('id', models.UUIDField(default=common.ids.uuid7, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('vector', common.vectors.VectorField(dimensions=256)),
                ('source_hash', models.CharField(max_length=64)),
                ('model', models.CharField(max_length=60)),
                ('created_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('product', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='ai_embedding', to='catalog.product')),
                ('tenant', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='platform.tenant')),
            ],
            options={
                'indexes': [common.vectors.HnswIndex(fields=['vector'], name='product_embedding_hnsw', opclasses=['vector_cosine_ops'])],
            },
        ),
        EnableRLS("AiUsage"),
        EnableRLS("ProductEmbedding"),
    ]
